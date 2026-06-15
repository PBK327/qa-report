import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const FILTER_DIMENSIONS = ['SPRINT', 'STATUS', 'PRIORITY', 'COMPONENTS', 'SCRUM_TEAM', 'SCOPE_CHANGE', 'BUG_CATEGORY'];
const ROW_COUNT_KEY = '__ROW_COUNT__';
const NONE_KEY = '__NONE__';
const KPI_STORAGE_KEY = 'exec-dashboard-kpi-by-dimension';
const RIGHT_AXIS_STORAGE_KEY = 'exec-dashboard-right-axis-by-dimension';
const TABLE_COLUMNS = [
  'BUGS',
  'STATUS',
  'PRIORITY',
  'COMPONENTS',
  'SCRUM_TEAM',
  'SCOPE_CHANGE',
  'SPRINT',
  'CUSTOMER_NAME',
  'TOTAL_BUGS',
  'EXECUTIVE_QUALITY_SCORE',
];

function asNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function isNumericValue(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function formatColumnLabel(key) {
  if (key === ROW_COUNT_KEY) return 'Row Count';
  if (key === NONE_KEY) return 'No Right Axis';
  return key.replaceAll('_', ' ');
}

function isAverageMetric(key) {
  return key.endsWith('_PCT') || key.endsWith('_DAYS') || key.includes('DURATION');
}

function aggregateMetric(rows, key) {
  const numbers = rows.map((row) => row[key]).filter(isNumericValue);
  if (!numbers.length) {
    return 0;
  }
  const total = numbers.reduce((sum, value) => sum + value, 0);
  const aggregated = isAverageMetric(key) ? total / numbers.length : total;
  return Number(aggregated.toFixed(1));
}

function uniqueValues(data, key) {
  return [...new Set(data.map((row) => row[key]).filter((v) => v !== null && v !== undefined && String(v).trim() !== ''))].sort();
}

function groupedCountData(data, groupBy, stackBy) {
  const groups = [...new Set(data.map((r) => r[groupBy] || 'Unknown'))].filter((g) => g !== 'Unknown').sort();
  const stacks = [...new Set(data.map((r) => r[stackBy] || 'Unknown'))].filter((s) => s !== 'Unknown').sort();
  const series = stacks.map((stack) => ({
    name: stack,
    type: 'bar',
    stack: 'total',
    data: groups.map((group) => data.filter((r) => (r[groupBy] || 'Unknown') === group && (r[stackBy] || 'Unknown') === stack).length),
  }));
  return { groups, series };
}

function groupedMetricData(data, groupBy, metrics) {
  const groups = [...new Set(data.map((r) => r[groupBy] || 'Unknown'))].filter((g) => g !== 'Unknown').sort();
  const series = metrics.map((metric) => ({
    name: metric.label,
    type: 'line',
    smooth: true,
    data: groups.map((group) => {
      const groupRows = data.filter((r) => (r[groupBy] || 'Unknown') === group);
      if (!groupRows.length) {
        return 0;
      }
      if (metric.key === ROW_COUNT_KEY) {
        return groupRows.length;
      }
      return aggregateMetric(groupRows, metric.key);
    }),
  }));
  return { groups, series };
}

function groupLabels(data, groupBy) {
  return [...new Set(data.map((row) => row[groupBy] || 'Unknown'))].filter((group) => group !== 'Unknown').sort();
}

function groupedMetricValues(data, groupBy, metricKey) {
  const groups = groupLabels(data, groupBy);
  const values = groups.map((group) => {
    const groupRows = data.filter((row) => (row[groupBy] || 'Unknown') === group);
    if (!groupRows.length) {
      return 0;
    }
    if (metricKey === ROW_COUNT_KEY) {
      return groupRows.length;
    }
    return aggregateMetric(groupRows, metricKey);
  });
  return { groups, values };
}

function metricConfigFor(key, metricOptions) {
  return metricOptions.find((metric) => metric.key === key) || metricOptions[0] || { key: ROW_COUNT_KEY, label: 'Row Count' };
}

function axisConfig(metricConfig, position = 'left') {
  const isPercentMetric = metricConfig.key.endsWith('_PCT');
  return {
    type: 'value',
    position,
    name: metricConfig.label,
    max: isPercentMetric ? 100 : null,
    axisLabel: isPercentMetric ? { formatter: '{value}%' } : undefined,
  };
}

function buildCartesianOptions({
  data,
  xKey,
  leftMetricKey,
  rightMetricKey,
  metricOptions,
  leftSeriesType = 'bar',
  rightSeriesType = 'line',
}) {
  const leftMetric = metricConfigFor(leftMetricKey, metricOptions);
  const rightMetric = rightMetricKey && rightMetricKey !== NONE_KEY ? metricConfigFor(rightMetricKey, metricOptions) : null;
  const left = groupedMetricValues(data, xKey, leftMetric.key);
  const right = rightMetric ? groupedMetricValues(data, xKey, rightMetric.key) : null;
  const groups = left.groups;

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: [leftMetric.label, ...(rightMetric ? [rightMetric.label] : [])], bottom: 0 },
    grid: { left: '3%', right: rightMetric ? '8%' : '4%', bottom: '15%', top: '10%', containLabel: true },
    xAxis: { type: 'category', data: groups, axisLabel: { rotate: 25 } },
    yAxis: [
      axisConfig(leftMetric, 'left'),
      ...(rightMetric ? [axisConfig(rightMetric, 'right')] : []),
    ],
    series: [
      {
        name: leftMetric.label,
        type: leftSeriesType,
        smooth: leftSeriesType === 'line',
        data: left.values,
        itemStyle: { color: '#2563eb', borderRadius: leftSeriesType === 'bar' ? [6, 6, 0, 0] : undefined },
        areaStyle: leftSeriesType === 'line' ? { opacity: 0.08 } : undefined,
      },
      ...(rightMetric
        ? [
            {
              name: rightMetric.label,
              type: rightSeriesType,
              smooth: rightSeriesType === 'line',
              yAxisIndex: 1,
              data: right.values,
              itemStyle: { color: '#0f766e', borderRadius: rightSeriesType === 'bar' ? [6, 6, 0, 0] : undefined },
              areaStyle: rightSeriesType === 'line' ? { opacity: 0.06 } : undefined,
            },
          ]
        : []),
    ],
  };
}

function groupedPieData(data, groupBy, valueKey) {
  const agg = {};
  for (const row of data) {
    const group = row[groupBy] || 'Unknown';
    const value = valueKey === 'count' ? 1 : asNumber(row[valueKey]);
    agg[group] = (agg[group] || 0) + value;
  }
  return Object.entries(agg)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

function useEchart(containerRef, options, onClick) {
  useEffect(() => {
    if (!containerRef.current) return undefined;
    const chart = echarts.init(containerRef.current);
    chart.setOption(options, true);
    if (onClick) {
      chart.off('click');
      chart.on('click', onClick);
    }

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.dispose();
    };
  }, [containerRef, options, onClick]);
}

export default function App() {
  const [rawData, setRawData] = useState([]);
  const [activeFilters, setActiveFilters] = useState({});
  const [summaryKpis, setSummaryKpis] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [kpiByDimension, setKpiByDimension] = useState(() => {
    try {
      const saved = window.localStorage.getItem(KPI_STORAGE_KEY);
      if (!saved) return {};
      const parsed = JSON.parse(saved);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  });
  const [rightKpiByDimension, setRightKpiByDimension] = useState(() => {
    try {
      const saved = window.localStorage.getItem(RIGHT_AXIS_STORAGE_KEY);
      if (!saved) return {};
      const parsed = JSON.parse(saved);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  });
  const [chartMetrics, setChartMetrics] = useState({
    priority: ROW_COUNT_KEY,
    component: 'TOTAL_BUGS',
    scope: ROW_COUNT_KEY,
  });
  const [rightAxisMetrics, setRightAxisMetrics] = useState({
    priority: NONE_KEY,
    scope: NONE_KEY,
  });
  const [chartGroupings, setChartGroupings] = useState({
    priority: 'PRIORITY',
    automation: 'SPRINT',
    component: 'COMPONENTS',
    scope: 'SPRINT',
  });
  const [tableSearch, setTableSearch] = useState('');
  const [sortCol, setSortCol] = useState('');
  const [sortAsc, setSortAsc] = useState(true);
  const [status, setStatus] = useState({ loading: true, error: '', source: '' });

  const priorityRef = useRef(null);
  const automationRef = useRef(null);
  const componentRef = useRef(null);
  const scopeRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    async function loadData() {
      setStatus({ loading: true, error: '', source: '' });
      try {
        const resp = await fetch(`${API_BASE}/api/dashboard/dataset`, { signal: controller.signal });
        if (!resp.ok) {
          throw new Error(`API failed with status ${resp.status}`);
        }
        const payload = await resp.json();
        setRawData(Array.isArray(payload.rows) ? payload.rows : []);
        setStatus({ loading: false, error: '', source: payload.source_table || '' });
      } catch (err) {
        if (err.name === 'AbortError') return;
        setStatus({ loading: false, error: err.message || 'Failed to load dashboard data', source: '' });
      }
    }
    loadData();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    window.localStorage.setItem(KPI_STORAGE_KEY, JSON.stringify(kpiByDimension));
  }, [kpiByDimension]);

  useEffect(() => {
    window.localStorage.setItem(RIGHT_AXIS_STORAGE_KEY, JSON.stringify(rightKpiByDimension));
  }, [rightKpiByDimension]);

  const availableDimensions = useMemo(() => {
    if (!rawData.length) {
      return FILTER_DIMENSIONS;
    }
    const keys = [...new Set(rawData.flatMap((row) => Object.keys(row || {})))];
    return keys
      .filter((key) => {
        const values = rawData.map((row) => row[key]).filter((value) => value !== null && value !== undefined && value !== '');
        if (!values.length) {
          return false;
        }
        return !values.every(isNumericValue);
      })
      .sort();
  }, [rawData]);

  const availableMetricOptions = useMemo(() => {
    if (!rawData.length) {
      return [{ key: ROW_COUNT_KEY, label: 'Row Count' }];
    }
    const keys = [...new Set(rawData.flatMap((row) => Object.keys(row || {})))];
    const numericKeys = keys
      .filter((key) => {
        const values = rawData.map((row) => row[key]).filter((value) => value !== null && value !== undefined && value !== '');
        if (!values.length) {
          return false;
        }
        return values.every(isNumericValue);
      })
      .sort();
    return [
      { key: ROW_COUNT_KEY, label: 'Row Count' },
      ...numericKeys.map((key) => ({ key, label: formatColumnLabel(key) })),
    ];
  }, [rawData]);

  const rightAxisOptions = useMemo(() => ([
    { key: NONE_KEY, label: 'No Right Axis' },
    ...availableMetricOptions,
  ]), [availableMetricOptions]);

  useEffect(() => {
    if (!availableDimensions.length) {
      return;
    }
    setChartGroupings((prev) => ({
      priority: availableDimensions.includes(prev.priority) ? prev.priority : availableDimensions[0],
      automation: availableDimensions.includes(prev.automation) ? prev.automation : availableDimensions[0],
      component: availableDimensions.includes(prev.component) ? prev.component : availableDimensions[0],
      scope: availableDimensions.includes(prev.scope) ? prev.scope : availableDimensions[0],
    }));
  }, [availableDimensions]);

  useEffect(() => {
    if (!availableMetricOptions.length) {
      return;
    }
    const validMetricKeys = new Set(availableMetricOptions.map((metric) => metric.key));
    setChartMetrics((prev) => ({
      priority: validMetricKeys.has(prev.priority) ? prev.priority : ROW_COUNT_KEY,
      component: validMetricKeys.has(prev.component) ? prev.component : availableMetricOptions[0].key,
      scope: validMetricKeys.has(prev.scope) ? prev.scope : ROW_COUNT_KEY,
    }));
    setKpiByDimension((prev) => {
      const next = { ...prev };
      for (const [dimension, metric] of Object.entries(next)) {
        if (!validMetricKeys.has(metric)) {
          next[dimension] = availableMetricOptions[0].key;
        }
      }
      return next;
    });
    setRightAxisMetrics((prev) => ({
      priority: prev.priority === NONE_KEY || validMetricKeys.has(prev.priority) ? prev.priority : NONE_KEY,
      scope: prev.scope === NONE_KEY || validMetricKeys.has(prev.scope) ? prev.scope : NONE_KEY,
    }));
    setRightKpiByDimension((prev) => {
      const next = { ...prev };
      for (const [dimension, metric] of Object.entries(next)) {
        if (metric !== NONE_KEY && !validMetricKeys.has(metric)) {
          next[dimension] = NONE_KEY;
        }
      }
      return next;
    });
  }, [availableMetricOptions]);

  // Fetch server-computed summary KPIs (non-dimensional, matches release_readiness_kpi.sql logic)
  useEffect(() => {
    const controller = new AbortController();
    async function loadSummary() {
      setSummaryLoading(true);
      try {
        const params = new URLSearchParams();
        for (const [k, v] of Object.entries(activeFilters)) {
          params.set(k, v);
        }
        const resp = await fetch(`${API_BASE}/api/dashboard/summary?${params.toString()}`, { signal: controller.signal });
        if (!resp.ok) throw new Error(`Summary API ${resp.status}`);
        const payload = await resp.json();
        setSummaryKpis(payload.kpis || null);
      } catch (err) {
        if (err.name !== 'AbortError') setSummaryKpis(null);
      } finally {
        setSummaryLoading(false);
      }
    }
    if (!status.loading) loadSummary();
    return () => controller.abort();
  }, [activeFilters, status.loading]);

  const filteredData = useMemo(() => {
    const filtered = rawData.filter((row) =>
      Object.entries(activeFilters).every(([key, val]) => String(row[key] || '') === String(val || ''))
    );

    const searched = tableSearch.trim()
      ? filtered.filter((row) => TABLE_COLUMNS.some((col) => String(row[col] ?? '').toLowerCase().includes(tableSearch.toLowerCase())))
      : filtered;

    if (!sortCol) {
      return searched;
    }

    return [...searched].sort((a, b) => {
      const av = a[sortCol] ?? '';
      const bv = b[sortCol] ?? '';
      const an = Number(av);
      const bn = Number(bv);
      if (Number.isFinite(an) && Number.isFinite(bn)) {
        return sortAsc ? an - bn : bn - an;
      }
      const as = String(av).toLowerCase();
      const bs = String(bv).toLowerCase();
      if (as < bs) return sortAsc ? -1 : 1;
      if (as > bs) return sortAsc ? 1 : -1;
      return 0;
    });
  }, [rawData, activeFilters, tableSearch, sortCol, sortAsc]);

  const kpis = useMemo(() => {
    const s = summaryKpis;
    const fmt = (val, decimals = 1) => (val == null ? '—' : Number(val).toFixed(decimals));
    const loading = summaryLoading || !s;
    return [
      { label: 'Executive Quality Score', value: loading ? '…' : fmt(s.EXECUTIVE_QUALITY_SCORE), tone: 'indigo' },
      { label: 'Total Bugs Detected',     value: loading ? '…' : (s.TOTAL_BUGS_DETECTED ?? 0), tone: 'red' },
      { label: 'Automation Coverage',     value: loading ? '…' : `${fmt(s.AUTOMATION_COVERAGE_PCT)}%`, tone: 'blue' },
      { label: 'Open Bug Rate',           value: loading ? '…' : `${fmt(s.OPEN_BUG_RATE_PCT)}%`, tone: 'amber' },
      { label: 'Completed Sprints',       value: loading ? '…' : (s.COMPLETED_SPRINTS ?? 0), tone: 'green' },
    ];
  }, [summaryKpis, summaryLoading]);

  const priorityOptions = useMemo(() => {
    return buildCartesianOptions({
      data: filteredData,
      xKey: chartGroupings.priority,
      leftMetricKey: chartMetrics.priority,
      rightMetricKey: rightAxisMetrics.priority,
      metricOptions: availableMetricOptions,
      leftSeriesType: 'bar',
      rightSeriesType: 'line',
    });
  }, [filteredData, chartGroupings.priority, chartMetrics.priority, rightAxisMetrics.priority, availableMetricOptions]);

  const automationOptions = useMemo(() => {
    return buildCartesianOptions({
      data: filteredData,
      xKey: chartGroupings.automation,
      leftMetricKey: kpiByDimension[chartGroupings.automation] || availableMetricOptions[0]?.key || ROW_COUNT_KEY,
      rightMetricKey: rightKpiByDimension[chartGroupings.automation] || NONE_KEY,
      metricOptions: availableMetricOptions,
      leftSeriesType: 'line',
      rightSeriesType: 'line',
    });
  }, [filteredData, chartGroupings.automation, kpiByDimension, rightKpiByDimension, availableMetricOptions]);

  const componentOptions = useMemo(() => {
    const groupBy = chartGroupings.component;
    const selectedMetric = metricConfigFor(chartMetrics.component, availableMetricOptions);
    const data = groupedPieData(filteredData, groupBy, selectedMetric.key === ROW_COUNT_KEY ? 'count' : selectedMetric.key);
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [
        {
          type: 'pie',
          radius: ['35%', '70%'],
          itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
          label: { formatter: '{b}\n{d}%' },
          data,
        },
      ],
    };
  }, [filteredData, chartGroupings.component, chartMetrics.component, availableMetricOptions]);

  const scopeOptions = useMemo(() => {
    return buildCartesianOptions({
      data: filteredData,
      xKey: chartGroupings.scope,
      leftMetricKey: chartMetrics.scope,
      rightMetricKey: rightAxisMetrics.scope,
      metricOptions: availableMetricOptions,
      leftSeriesType: 'bar',
      rightSeriesType: 'line',
    });
  }, [filteredData, chartGroupings.scope, chartMetrics.scope, rightAxisMetrics.scope, availableMetricOptions]);

  useEchart(priorityRef, priorityOptions, (params) => {
    setActiveFilters((prev) => ({ ...prev, [chartGroupings.priority]: params.name }));
  });

  useEchart(automationRef, automationOptions, null);

  useEchart(componentRef, componentOptions, (params) => {
    setActiveFilters((prev) => ({ ...prev, [chartGroupings.component]: params.name }));
  });

  useEchart(scopeRef, scopeOptions, (params) => {
    setActiveFilters((prev) => ({ ...prev, [chartGroupings.scope]: params.name }));
  });

  function setFilter(key, value) {
    setActiveFilters((prev) => {
      const next = { ...prev };
      if (!value || value === 'All') delete next[key];
      else next[key] = value;
      return next;
    });
  }

  if (status.loading) {
    return <div className="loading-screen">Loading dashboard data from Vertica...</div>;
  }

  if (status.error) {
    return <div className="loading-screen error">{status.error}</div>;
  }

  return (
    <div className="page-shell">
      <header className="hero">
        <div>
          <h1>Executive Quality Dashboard</h1>
          <p>Live release quality overview powered by Vertica tables.</p>
          <div className="source-chip">Source table: {status.source || 'unknown'}</div>
        </div>
        <div className="hero-actions">
          <button className="btn btn-secondary" onClick={() => { setActiveFilters({}); setTableSearch(''); }}>
            Reset Filters
          </button>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Refresh Data
          </button>
        </div>
      </header>

      <section className="panel filters-panel">
        {FILTER_DIMENSIONS.map((dim) => (
          <label key={dim}>
            <span>{dim.replaceAll('_', ' ')}</span>
            <select value={activeFilters[dim] || 'All'} onChange={(e) => setFilter(dim, e.target.value)}>
              <option value="All">All {dim.replaceAll('_', ' ')}</option>
              {uniqueValues(rawData, dim).map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
        ))}
      </section>

      <section className="kpi-grid">
        {kpis.map((kpi) => (
          <article key={kpi.label} className={`panel kpi-card tone-${kpi.tone}`}>
            <h3>{kpi.label}</h3>
            <p>{kpi.value}</p>
          </article>
        ))}
      </section>

      <section className="chart-grid two">
        <article className="panel">
          <div className="chart-head">
            <h3>Bugs by {chartGroupings.priority.replaceAll('_', ' ')}</h3>
            <div className="chart-controls">
              <select value={chartGroupings.priority} onChange={(e) => setChartGroupings((prev) => ({ ...prev, priority: e.target.value }))}>
                {availableDimensions.map((dim) => <option key={dim} value={dim}>{formatColumnLabel(dim)}</option>)}
              </select>
              <select value={chartMetrics.priority} onChange={(e) => setChartMetrics((prev) => ({ ...prev, priority: e.target.value }))}>
                {availableMetricOptions.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
              </select>
              <select value={rightAxisMetrics.priority} onChange={(e) => setRightAxisMetrics((prev) => ({ ...prev, priority: e.target.value }))}>
                {rightAxisOptions.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
              </select>
            </div>
          </div>
          <div className="chart" ref={priorityRef} />
        </article>
        <article className="panel">
          <div className="chart-head">
            <h3>Metrics by {chartGroupings.automation.replaceAll('_', ' ')}</h3>
            <div className="chart-controls">
              <select value={chartGroupings.automation} onChange={(e) => setChartGroupings((prev) => ({ ...prev, automation: e.target.value }))}>
                {availableDimensions.map((dim) => <option key={dim} value={dim}>{formatColumnLabel(dim)}</option>)}
              </select>
              <select
                value={kpiByDimension[chartGroupings.automation] || availableMetricOptions[0]?.key || ROW_COUNT_KEY}
                onChange={(e) => {
                  const selectedDimension = chartGroupings.automation;
                  setKpiByDimension((prev) => ({ ...prev, [selectedDimension]: e.target.value }));
                }}
              >
                {availableMetricOptions.map((kpi) => <option key={kpi.key} value={kpi.key}>{kpi.label}</option>)}
              </select>
              <select
                value={rightKpiByDimension[chartGroupings.automation] || NONE_KEY}
                onChange={(e) => {
                  const selectedDimension = chartGroupings.automation;
                  setRightKpiByDimension((prev) => ({ ...prev, [selectedDimension]: e.target.value }));
                }}
              >
                {rightAxisOptions.map((kpi) => <option key={kpi.key} value={kpi.key}>{kpi.label}</option>)}
              </select>
            </div>
          </div>
          <div className="chart" ref={automationRef} />
        </article>
      </section>

      <section className="chart-grid three">
        <article className="panel">
          <div className="chart-head">
            <h3>Bugs by {chartGroupings.component.replaceAll('_', ' ')}</h3>
            <div className="chart-controls">
              <select value={chartGroupings.component} onChange={(e) => setChartGroupings((prev) => ({ ...prev, component: e.target.value }))}>
                {availableDimensions.map((dim) => <option key={dim} value={dim}>{formatColumnLabel(dim)}</option>)}
              </select>
              <select value={chartMetrics.component} onChange={(e) => setChartMetrics((prev) => ({ ...prev, component: e.target.value }))}>
                {availableMetricOptions.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
              </select>
            </div>
          </div>
          <div className="chart" ref={componentRef} />
        </article>
        <article className="panel span-2">
          <div className="chart-head">
            <h3>Trends by {chartGroupings.scope.replaceAll('_', ' ')}</h3>
            <div className="chart-controls">
              <select value={chartGroupings.scope} onChange={(e) => setChartGroupings((prev) => ({ ...prev, scope: e.target.value }))}>
                {availableDimensions.map((dim) => <option key={dim} value={dim}>{formatColumnLabel(dim)}</option>)}
              </select>
              <select value={chartMetrics.scope} onChange={(e) => setChartMetrics((prev) => ({ ...prev, scope: e.target.value }))}>
                {availableMetricOptions.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
              </select>
              <select value={rightAxisMetrics.scope} onChange={(e) => setRightAxisMetrics((prev) => ({ ...prev, scope: e.target.value }))}>
                {rightAxisOptions.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
              </select>
            </div>
          </div>
          <div className="chart" ref={scopeRef} />
        </article>
      </section>

      <section className="panel table-panel">
        <div className="table-toolbar">
          <h3>Detailed Execution and Bug Records</h3>
          <input
            value={tableSearch}
            onChange={(e) => setTableSearch(e.target.value)}
            placeholder="Search bugs, assignees, components..."
          />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {TABLE_COLUMNS.map((col) => (
                  <th
                    key={col}
                    onClick={() => {
                      if (sortCol === col) setSortAsc((v) => !v);
                      else {
                        setSortCol(col);
                        setSortAsc(true);
                      }
                    }}
                  >
                    {col.replaceAll('_', ' ')} {sortCol === col ? (sortAsc ? '▲' : '▼') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredData.slice(0, 1500).map((row, idx) => (
                <tr key={`${row.BUGS || 'row'}-${idx}`}>
                  {TABLE_COLUMNS.map((col) => <td key={col}>{row[col] ?? '-'}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
