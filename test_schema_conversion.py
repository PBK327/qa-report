#!/usr/bin/env python3
"""
Test script to demonstrate schema type conversion.

This script shows how the schema mapping works by converting
sample DataFrame columns to proper types.

Usage:
    python3 test_schema_conversion.py
"""

import pandas as pd
from qa_pipeline.schema import (
    AGG_TEST_FACT_SCHEMA,
    DEFECT_DIM_SCHEMA,
    convert_df_to_schema,
    describe_schema,
    _to_datetime,
    _to_int,
    _to_float,
    _to_bool,
)


def test_type_converters():
    """Test individual type converter functions."""
    print("=" * 70)
    print("TYPE CONVERTER FUNCTIONS TEST")
    print("=" * 70)
    
    print("\n1. DateTime Converter")
    print(f"   _to_datetime('2026-06-07 10:30:00') = {_to_datetime('2026-06-07 10:30:00')}")
    print(f"   _to_datetime('') = {_to_datetime('')}")
    print(f"   _to_datetime('invalid') = {_to_datetime('invalid')}")
    
    print("\n2. Integer Converter")
    print(f"   _to_int('123') = {_to_int('123')}")
    print(f"   _to_int('123.0') = {_to_int('123.0')}")
    print(f"   _to_int('') = {_to_int('')}")
    print(f"   _to_int('invalid') = {_to_int('invalid')}")
    
    print("\n3. Float Converter")
    print(f"   _to_float('45.67') = {_to_float('45.67')}")
    print(f"   _to_float('45') = {_to_float('45')}")
    print(f"   _to_float('') = {_to_float('')}")
    
    print("\n4. Boolean Converter")
    print(f"   _to_bool('Yes') = {_to_bool('Yes')}")
    print(f"   _to_bool('True') = {_to_bool('True')}")
    print(f"   _to_bool('Done') = {_to_bool('Done')}")
    print(f"   _to_bool('No') = {_to_bool('No')}")
    print(f"   _to_bool('') = {_to_bool('')}")


def test_dataframe_conversion():
    """Test converting a sample DataFrame using schema."""
    print("\n\n" + "=" * 70)
    print("DATAFRAME SCHEMA CONVERSION TEST")
    print("=" * 70)
    
    # Create sample DataFrame with TEXT data (as read from SQLite)
    sample_data = {
        'Issue key': ['AUTO-001', 'AUTO-002', 'AUTO-003'],
        'Created': ['2026-06-07T10:30:00', '2026-06-08T14:45:00', '2026-06-09T09:15:00'],
        'No of Test Scenario': ['45', '78', '52'],
        'Test Pass %': ['95.5', '87.3', '100.0'],
        'Story Points': ['8.0', '13.0', '5.0'],
        'Custom field (Automation Test Run Approved)': ['Yes', 'No', 'Yes'],
        'Custom field (Job Name)': ['BI-Sanity', 'ADM-Full', 'PAM-Integration'],
    }
    
    df_text = pd.DataFrame(sample_data)
    
    print("\nBEFORE conversion (TEXT storage):")
    print(df_text)
    print("\nData types BEFORE:")
    print(df_text.dtypes)
    
    # Apply schema conversion for only the columns we have
    mini_schema = [
        col_schema for col_schema in AGG_TEST_FACT_SCHEMA
        if col_schema.name in df_text.columns
    ]
    
    df_typed = convert_df_to_schema(df_text, mini_schema, strict=False)
    
    print("\n\nAFTER conversion (with schema):")
    print(df_typed)
    print("\nData types AFTER:")
    print(df_typed.dtypes)
    
    print("\n\nVERIFICATION - Operations that now work correctly:")
    print(f"  ✓ Max Created date: {df_typed['Created'].max()}")
    print(f"  ✓ Mean Test Pass %: {df_typed['Test Pass %'].mean():.2f}")
    print(f"  ✓ Sum Scenarios: {df_typed['No of Test Scenario'].sum()}")
    print(f"  ✓ Approved count: {df_typed['Custom field (Automation Test Run Approved)'].sum()}")
    
    print("\n\nSORT TEST - Chronological order:")
    sorted_df = df_typed.sort_values('Created')
    print(f"  Sorted order: {sorted_df['Issue key'].tolist()}")


def test_schema_descriptions():
    """Display schema descriptions."""
    print("\n\n" + "=" * 70)
    print("SCHEMA DEFINITIONS")
    print("=" * 70)
    
    print("\nAGG_TEST_FACT Schema (showing first 10 columns):")
    print(describe_schema(AGG_TEST_FACT_SCHEMA[:10]))
    
    print("\n\nDEFECT_DIM Schema (showing first 10 columns):")
    print(describe_schema(DEFECT_DIM_SCHEMA[:10]))


if __name__ == "__main__":
    test_type_converters()
    test_dataframe_conversion()
    test_schema_descriptions()
    
    print("\n\n" + "=" * 70)
    print("✅ All schema conversion tests completed successfully!")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Run: python -m qa_pipeline.cli show-schema agg-fact")
    print("  2. Run: python -m qa_pipeline.cli verify-types")
    print("  3. Run: python -m qa_pipeline.cli export-typed")
