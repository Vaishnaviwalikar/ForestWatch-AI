import os
import sys

def get_coordinates_from_user():
    """
    Get coordinates from user.
    Uses GUI dialog if display is available; falls back to console prompt.
    """
    has_display = bool(os.environ.get("DISPLAY") or sys.platform == "darwin")

    # If terminal or user chooses console
    if not has_display or "--cli" in sys.argv:
        return _get_coords_console()

    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog

        root = tk.Tk()
        root.withdraw()

        choice = messagebox.askyesno(
            "Area Selection",
            "Choose input method:\n\nYES - Enter coordinates manually\nNO - Use default / console input"
        )

        if choice:
            lat = float(simpledialog.askstring("Latitude", "Enter latitude (-90 to 90):", initialvalue="15.0000"))
            lon = float(simpledialog.askstring("Longitude", "Enter longitude (-180 to 180):", initialvalue="75.0000"))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                root.destroy()
                return lat, lon
        root.destroy()
    except Exception:
        pass

    return _get_coords_console()


def _get_coords_console():
    """Console-based coordinate prompt"""
    print("\nEnter coordinates for Sentinel-2 analysis:")
    try:
        lat_in = input("Latitude [-90 to 90] (default: 15.0000): ").strip()
        lat = float(lat_in) if lat_in else 15.0000

        lon_in = input("Longitude [-180 to 180] (default: 75.0000): ").strip()
        lon = float(lon_in) if lon_in else 75.0000

        return lat, lon
    except ValueError:
        print("Invalid input! Using defaults (15.0, 75.0).")
        return 15.0, 75.0


def get_date_range():
    """Get baseline and recent date ranges for multi-temporal analysis"""
    print("\nEnter multi-temporal date ranges:")
    try:
        b_start = input("Baseline Start Date [YYYY-MM-DD] (default: 2022-01-01): ").strip() or "2022-01-01"
        b_end = input("Baseline End Date [YYYY-MM-DD] (default: 2022-05-31): ").strip() or "2022-05-31"
        r_start = input("Recent Start Date [YYYY-MM-DD] (default: 2023-01-01): ").strip() or "2023-01-01"
        r_end = input("Recent End Date [YYYY-MM-DD] (default: 2023-05-31): ").strip() or "2023-05-31"

        return (b_start, b_end), (r_start, r_end)
    except Exception:
        return ("2022-01-01", "2022-05-31"), ("2023-01-01", "2023-05-31")
