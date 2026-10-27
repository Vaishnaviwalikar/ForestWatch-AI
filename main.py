import os
import sys
import uuid
import argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

import Anni_code
from area_selector import get_coordinates_from_user, get_date_range
from show_results import show_results


def main():
    parser = argparse.ArgumentParser(description="Sentinel-2 Multi-Temporal Forest & Deforestation Monitor")
    parser.add_argument("--lat", type=float, default=None, help="Latitude (-90 to 90)")
    parser.add_argument("--lon", type=float, default=None, help="Longitude (-180 to 180)")
    parser.add_argument("--bstart", type=str, default="2022-01-01", help="Baseline Start Date (YYYY-MM-DD)")
    parser.add_argument("--bend", type=str, default="2022-05-31", help="Baseline End Date (YYYY-MM-DD)")
    parser.add_argument("--rstart", type=str, default="2023-01-01", help="Recent Start Date (YYYY-MM-DD)")
    parser.add_argument("--rend", type=str, default="2023-05-31", help="Recent End Date (YYYY-MM-DD)")
    parser.add_argument("--radius", type=float, default=2000, help="AOI radius in meters")
    parser.add_argument("--cloud", type=float, default=20, help="Max cloud percentage")
    parser.add_argument("--no-gui", action="store_true", help="Run in headless non-interactive mode")

    args = parser.parse_args()

    # Get coordinates and dates
    if args.lat is not None and args.lon is not None:
        latitude, longitude = args.lat, args.lon
        baseline_start, baseline_end = args.bstart, args.bend
        recent_start, recent_end = args.rstart, args.rend
    elif args.no_gui:
        latitude, longitude = 15.0000, 75.0000
        baseline_start, baseline_end = "2022-01-01", "2022-05-31"
        recent_start, recent_end = "2023-01-01", "2023-05-31"
    else:
        print("\n=======================================================")
        print("  Sentinel-2 Satellite Forest & Deforestation Monitor  ")
        print("=======================================================")
        latitude, longitude = get_coordinates_from_user()
        (baseline_start, baseline_end), (recent_start, recent_end) = get_date_range()

    print(f"\nTarget Location: Latitude {latitude}°, Longitude {longitude}°")
    print(f"Baseline Window: {baseline_start} to {baseline_end}")
    print(f"Recent Window:   {recent_start} to {recent_end}")

    # Generate unique analysis ID
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    analysis_id = f"cli_{timestamp}_{uuid.uuid4().hex[:6]}"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
        "recent_start": recent_start,
        "recent_end": recent_end,
        "radius_meters": args.radius,
        "max_cloud_pct": args.cloud
    }

    print(f"\nInitiating analysis job: {analysis_id}...")
    result = Anni_code.run_analysis_pipeline(analysis_id, params=params)

    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)
    change_stats = result["summary"]["change_stats"]
    print(f"Deforestation Alert:     {change_stats['risk_level']}")
    print(f"Detected Forest Loss:    {change_stats['deforested']['hectares']:.2f} ha ({change_stats['deforested']['percentage']:.2f}%)")
    print(f"Stable Dense Forest:    {change_stats['stable_dense']['hectares']:.2f} ha ({change_stats['stable_dense']['percentage']:.2f}%)")
    print(f"Mean NDVI Delta:         {change_stats['mean_delta_ndvi']:+.4f}")
    print(f"Report File:             {result['report_path']}")
    print(f"Spatial Change Map:      {result['map_path']}")
    print(f"Statistical Charts:      {result['chart_path']}")

    if not args.no_gui:
        show_results(analysis_id=analysis_id)


if __name__ == "__main__":
    main()
