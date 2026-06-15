from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import vertica_python
except Exception:  # pragma: no cover
    vertica_python = None

from qa_pipeline.config import load_pipeline_config


LOCKED_DASHBOARD_TABLE = 'AGG_QA_REPORT_DAY'

# Columns allowed as WHERE-clause filters (prevents SQL injection)
_ALLOWED_FILTER_COLS = frozenset({
    'SPRINT', 'STATUS', 'PRIORITY', 'COMPONENTS', 'SCRUM_TEAM',
    'SCOPE_CHANGE', 'BUG_CATEGORY', 'ENV_NAME', 'ENV_VERSION',
    'TEST_JOB_NAME', 'ASSIGNEE', 'CUSTOMER_NAME', 'BUG_ORIGIN',
})


@dataclass
class ServerConfig:
    host: str = '0.0.0.0'
    port: int = 8000
    ui_dist: Path = Path('exec_dashboard_ui/dist')
    default_table: str = LOCKED_DASHBOARD_TABLE


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _sanitize_table_name(raw_name: str) -> str:
    table_name = (raw_name or '').strip().upper()
    if not table_name:
        raise ValueError('Table name cannot be empty.')
    if not table_name.startswith('AGG_'):
        raise ValueError('Only AGG_ tables are allowed for dashboard dataset queries.')
    allowed = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')
    if any(ch not in allowed for ch in table_name):
        raise ValueError('Invalid table name format.')
    return table_name


def _resolve_dashboard_table(requested_table: str | None) -> str:
    if requested_table is None:
        return LOCKED_DASHBOARD_TABLE
    safe = _sanitize_table_name(requested_table)
    if safe != LOCKED_DASHBOARD_TABLE:
        raise ValueError(f'Dashboard table is hard-locked to {LOCKED_DASHBOARD_TABLE}.')
    return safe


def _candidate_hosts(host: str) -> list[str]:
    h = (host or '').strip()
    if not h:
        return ['localhost']
    if h in {'localhost', '127.0.0.1', '::1'}:
        return [h, 'host.docker.internal', '127.0.0.1']
    return [h]


def _connect_vertica():
    if vertica_python is None:
        raise RuntimeError('vertica-python is not installed. Run: pip install vertica-python')

    cfg = load_pipeline_config().vertica
    if cfg is None:
        raise RuntimeError('Vertica config missing in app_config.json under the vertica block.')

    errors = []
    for host in _candidate_hosts(cfg.host):
        try:
            conn = vertica_python.connect(
                host=host,
                port=cfg.port,
                database=cfg.database,
                user=cfg.user,
                password=cfg.password,
                autocommit=True,
                connection_timeout=8,
            )
            return conn, cfg
        except Exception as exc:  # pragma: no cover
            errors.append(f'{host}:{cfg.port} -> {exc}')

    raise RuntimeError('Failed to connect to Vertica: ' + '; '.join(errors))


def _fetch_rows(table: str, limit: int = 4000) -> list[dict]:
    conn, cfg = _connect_vertica()
    safe_table = _sanitize_table_name(table)
    full = f'{_q(cfg.schema)}.{_q(safe_table)}'
    sql = f'SELECT * FROM {full} ORDER BY 1 DESC LIMIT {int(limit)}'
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
    finally:
        conn.close()

    out = []
    for row in rows:
        item = {}
        for idx, col in enumerate(cols):
            val = row[idx]
            if val is None:
                item[col.upper()] = None
            elif isinstance(val, Decimal):
                item[col.upper()] = float(val)
            elif hasattr(val, 'isoformat'):
                item[col.upper()] = val.isoformat()
            else:
                item[col.upper()] = val
        out.append(item)
    return out


def _fetch_summary(filters: dict) -> dict:
    """Run the non-dimensional KPI query (from release_readiness_kpi.sql logic)
    with optional WHERE-clause filters. Returns a single summary dict."""
    conn, cfg = _connect_vertica()
    schema = cfg.schema

    # Build parameterised WHERE clause from validated filter columns only
    where_parts = []
    params = []
    for col, val in filters.items():
        col_upper = col.strip().upper()
        if col_upper not in _ALLOWED_FILTER_COLS:
            continue
        where_parts.append(f'{_q(col_upper)} = %s')
        params.append(val)

    where_clause = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    sql = f"""
        SELECT
            COUNT(DISTINCT executed_test)                                                      AS total_automated_tests,
            COUNT(DISTINCT CASE WHEN UPPER(auto_test_run_status) = 'PASS'
                                THEN executed_test END)                                        AS passed_tests,
            ROUND(100.0 * COUNT(DISTINCT CASE WHEN UPPER(auto_test_run_status) = 'PASS'
                                              THEN executed_test END)
                  / NULLIF(COUNT(DISTINCT executed_test), 0), 2)                               AS execution_success_rate_pct,
            ROUND(100.0 * COUNT(DISTINCT executed_test) / MAX(total_test), 2)                  AS automation_coverage_pct,
            COUNT(DISTINCT CASE WHEN QA_Report = 'Automation' THEN Bugs END)                   AS bugs_detected_by_automation,
            COUNT(DISTINCT Bugs)                                                                AS total_bugs_detected,
            ROUND(
                COALESCE(
                    100.0 * SUM(COALESCE(open_bugs, 0))
                    / NULLIF(SUM(COALESCE(open_bugs, 0)) + SUM(COALESCE(closed_bugs, 0)), 0),
                    0
                ),
                2
            )                                                                                  AS open_bug_rate_pct,
            ROUND(
                COALESCE(
                    ROUND(100.0 * COUNT(DISTINCT CASE WHEN UPPER(auto_test_run_status) = 'PASS'
                                                       THEN executed_test END)
                          / NULLIF(COUNT(DISTINCT executed_test), 0), 2),
                    0
                ) * 0.40
                + COALESCE(
                    100 - (
                        100.0 * SUM(COALESCE(open_bugs, 0))
                        / NULLIF(SUM(COALESCE(open_bugs, 0)) + SUM(COALESCE(closed_bugs, 0)), 0)
                    ),
                    100
                ) * 0.40
                + COALESCE(
                    CASE WHEN AVG(resolution_days) >= 100 THEN 0
                         ELSE 100 - AVG(resolution_days) END,
                    100
                ) * 0.20,
                2)                                                                             AS executive_quality_score,
            SUM(total_bugs)                                                                     AS total_bugs,
            SUM(regression_bugs)                                                                AS regression_bugs,
            ROUND(COALESCE(AVG(resolution_days), 0), 2)                                         AS avg_resolution_days,
            COUNT(DISTINCT CASE WHEN sprint_status = 'Completed' THEN Sprint END)               AS completed_sprints
        FROM {_q(schema)}.{_q(LOCKED_DASHBOARD_TABLE)} FAGG
        {where_clause}
    """

    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        cols = [desc[0].upper() for desc in cur.description]
    finally:
        conn.close()

    if not row:
        return {}

    result = {}
    for idx, col in enumerate(cols):
        val = row[idx]
        if val is None:
            result[col] = None
        elif isinstance(val, Decimal):
            result[col] = float(val)
        elif hasattr(val, 'isoformat'):
            result[col] = val.isoformat()
        else:
            result[col] = val
    return result


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def _write_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET,OPTIONS')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/health':
            self._write_json({'ok': True, 'service': 'exec-dashboard-server'})
            return

        if parsed.path == '/api/dashboard/dataset':
            try:
                params = parse_qs(parsed.query)
                requested_table = params.get('table', [None])[0]
                table_name = _resolve_dashboard_table(requested_table)
                row_limit = int(params.get('limit', ['4000'])[0])
                rows = _fetch_rows(table_name, row_limit)
                self._write_json({'rows': rows, 'source_table': table_name, 'count': len(rows)})
            except Exception as exc:
                self._write_json({'error': str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if parsed.path == '/api/dashboard/summary':
            try:
                params = parse_qs(parsed.query)
                # Each filter param is a single value; drop list wrapping
                filters = {k: v[0] for k, v in params.items()}
                summary = _fetch_summary(filters)
                self._write_json({'kpis': summary})
            except Exception as exc:
                self._write_json({'error': str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # SPA fallback: serve index.html when path not found in dist.
        if parsed.path.startswith('/api/'):
            self._write_json({'error': 'Not found'}, status=404)
            return

        file_candidate = (Path(self.directory or '.') / parsed.path.lstrip('/')).resolve()
        base_dir = Path(self.directory or '.').resolve()
        if parsed.path in {'', '/'} or not str(file_candidate).startswith(str(base_dir)) or not file_candidate.exists():
            self.path = '/index.html'

        return super().do_GET()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ui_dist = root / os.environ.get('EXEC_DASH_UI_DIST', 'exec_dashboard_ui/dist')

    if not ui_dist.exists():
        print('UI dist folder not found. Build React app first:')
        print('  cd exec_dashboard_ui && npm install && npm run build')

    cfg = ServerConfig(
        host=os.environ.get('EXEC_DASH_HOST', '0.0.0.0'),
        port=int(os.environ.get('EXEC_DASH_PORT', '8000')),
        ui_dist=ui_dist,
        default_table=LOCKED_DASHBOARD_TABLE,
    )

    handler = lambda *args, **kwargs: DashboardHandler(*args, directory=str(cfg.ui_dist), **kwargs)
    server = ThreadingHTTPServer((cfg.host, cfg.port), handler)
    print(f'Exec dashboard server running at http://{cfg.host}:{cfg.port}')
    print(f'Dashboard table lock: {cfg.default_table}')
    server.serve_forever()


if __name__ == '__main__':
    main()
