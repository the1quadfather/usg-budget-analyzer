"""
analysis/report_generator.py

Serializes Polars DataFrames into a formatted, multi-tab Excel workbook.
Applies conditional formatting and strict column typing for executive reporting.
"""

import logging
from pathlib import Path
import polars as pl
import xlsxwriter
import xlsxwriter.utility

logger = logging.getLogger(__name__)

class ExcelReportGenerator:
    def __init__(self, output_dir: str = "data/processed"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _apply_sparklines(self, wb: xlsxwriter.Workbook, df: pl.DataFrame, sheet_name: str):
        """Helper method to draw inline sparkline charts in Excel."""
        if "Trend" not in df.columns:
            return
            
        ws = wb.get_worksheet_by_name(sheet_name)
        year_cols = [c for c in df.columns if c.isdigit()]
        
        if not year_cols:
            return

        # Find column indices (0-indexed for xlsxwriter)
        start_col_idx = df.columns.index(year_cols[0])
        end_col_idx = df.columns.index(year_cols[-1])
        trend_col_idx = df.columns.index("Trend")

        # Excel rows are 0-indexed, row 0 is the header. Data starts at row 1.
        for row_num in range(1, len(df) + 1):
            start_cell = xlsxwriter.utility.xl_rowcol_to_cell(row_num, start_col_idx)
            end_cell = xlsxwriter.utility.xl_rowcol_to_cell(row_num, end_col_idx)
            trend_cell = xlsxwriter.utility.xl_rowcol_to_cell(row_num, trend_col_idx)

            # Draw a column sparkline highlighting the highest and lowest funding years
            ws.add_sparkline(trend_cell, {
                'range': f"{start_cell}:{end_cell}",
                'type': 'column',
                'style': 10,  # Built-in Excel styling
                'high_point': True,
                'low_point': True
            })
            
        # Widen the Trend column so the sparkline is readable
        ws.set_column(trend_col_idx, trend_col_idx, 20)

    def generate_executive_report(
        self, df_gaps: pl.DataFrame, df_trends: pl.DataFrame,
        df_pe_trends: pl.DataFrame = None, filename: str = "DoD_Budget_Analysis.xlsx"
    ) -> Path:
        output_path = self.output_dir / filename

        try:
            currency_format = {"num_format": "$#,##0"}
            percent_format = {"num_format": "0.00%"}
            negative_red = {
                "type": "cell", "criteria": "<", "value": 0,
                "format": {"font_color": "#9C0006", "bg_color": "#FFC7CE"}
            }

            with xlsxwriter.Workbook(str(output_path)) as wb:
                # --- Sheet 1: Gap Analysis ---
                if not df_gaps.is_empty():
                    funding_cols = [col for col in df_gaps.columns if "_$K" in col]
                    df_gaps.write_excel(
                        workbook=wb, worksheet="Gap Analysis", autofit=True,
                        header_format={"bold": True, "bg_color": "#D3D3D3"},
                        column_formats={col: currency_format for col in funding_cols},
                        conditional_formats={"YoY_Change_%": negative_red}
                    )

                # --- Sheet 2: Macro Trends ---
                if not df_trends.is_empty():
                    year_cols = [col for col in df_trends.columns if col.isdigit()]
                    df_trends.write_excel(
                        workbook=wb, worksheet="Agency Macro Trends", autofit=True,
                        header_format={"bold": True, "bg_color": "#D3D3D3"},
                        column_formats={col: currency_format for col in year_cols},
                        conditional_formats={"total_delta_pct": negative_red, "cagr_pct": negative_red}
                    )
                    self._apply_sparklines(wb, df_trends, "Agency Macro Trends")
                    
                # --- Sheet 3: Granular PE Trends ---
                if df_pe_trends is not None and not df_pe_trends.is_empty():
                    year_cols = [col for col in df_pe_trends.columns if col.isdigit()]
                    df_pe_trends.write_excel(
                        workbook=wb, worksheet="Program Element Trends", autofit=True,
                        header_format={"bold": True, "bg_color": "#D3D3D3"},
                        column_formats={col: currency_format for col in year_cols},
                        conditional_formats={"total_delta_pct": negative_red, "cagr_pct": negative_red}
                    )
                    self._apply_sparklines(wb, df_pe_trends, "Program Element Trends")

            logger.info(f"Report successfully generated at: {output_path.absolute()}")
            return output_path.absolute()

        except Exception as e:
            logger.error(f"Failed to generate Excel report: {e}")
            raise