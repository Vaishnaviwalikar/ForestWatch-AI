import os
import sys
import webbrowser
import logging

logger = logging.getLogger(__name__)

BASE_OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "static", "sentinel_output"))


def show_results(analysis_id=None):
    """
    Display analysis results for the specified analysis_id or latest run.
    """
    if analysis_id:
        target_dir = os.path.join(BASE_OUTPUT_DIR, analysis_id)
        report_path = os.path.join(target_dir, f"forest_analysis_{analysis_id}.txt")
        chart_path = os.path.join(target_dir, f"forest_classification_{analysis_id}.png")
        map_path = os.path.join(target_dir, f"temporal_comparison_{analysis_id}.png")
    else:
        target_dir = BASE_OUTPUT_DIR
        report_path = os.path.join(BASE_OUTPUT_DIR, "forest_analysis.txt")
        chart_path = os.path.join(BASE_OUTPUT_DIR, "forest_classification.png")
        map_path = os.path.join(BASE_OUTPUT_DIR, "temporal_comparison.png")

    # Display text report to console
    if os.path.exists(report_path):
        print("\n" + "=" * 60)
        print("FOREST ANALYSIS REPORT")
        print("=" * 60)
        with open(report_path, 'r') as f:
            print(f.read())
    else:
        print(f"Report file not found: {report_path}")

    # Open visualizations in browser/viewer
    for img_path in [map_path, chart_path]:
        if os.path.exists(img_path):
            print(f"Image ready: {img_path}")
            try:
                if "--no-browser" not in sys.argv:
                    webbrowser.open(f"file://{img_path}")
            except Exception as e:
                logger.warning(f"Could not open image viewer: {e}")


if __name__ == "__main__":
    aid = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    show_results(analysis_id=aid)
