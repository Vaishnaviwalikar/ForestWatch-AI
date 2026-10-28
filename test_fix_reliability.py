import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import Anni_code
import gee_data_loader
from incident_service import IncidentService

class TestFixReliability(unittest.TestCase):

    def test_fix1_gee_failure_does_not_silently_fallback(self):
        """Fix 1: In real analysis mode (demo_mode=False), Earth Engine failure must raise RuntimeError, never return synthetic data silently."""
        with patch.object(gee_data_loader, 'fetch_sentinel2_bands', side_effect=Exception("GEE connection timed out")):
            with self.assertRaises(RuntimeError) as ctx:
                gee_data_loader.fetch_bitemporal_sentinel2(
                    lat=15.0, lon=75.0,
                    baseline_start="2022-01-01", baseline_end="2022-05-31",
                    recent_start="2023-01-01", recent_end="2023-05-31",
                    demo_mode=False
                )
            self.assertIn("DATA_UNAVAILABLE", str(ctx.exception))

    def test_fix1_explicit_demo_mode_labelled_and_cannot_create_incidents(self):
        """Fix 1: Explicit demo_mode=True must carry unmistakable DEMO labels and be rejected by incident service."""
        with patch.object(gee_data_loader, 'fetch_sentinel2_bands', side_effect=Exception("GEE offline")):
            base, rec = gee_data_loader.fetch_bitemporal_sentinel2(
                lat=15.0, lon=75.0,
                baseline_start="2022-01-01", baseline_end="2022-05-31",
                recent_start="2023-01-01", recent_end="2023-05-31",
                demo_mode=True
            )
            b4_base, b8_base, meta_base = base
            b4_rec, b8_rec, meta_rec = rec

            self.assertTrue(meta_rec.get("is_demo_data"))
            self.assertEqual(meta_rec.get("processing_mode"), "DEMO")
            self.assertEqual(meta_rec.get("data_source"), "DEMO_SYNTHETIC")
            self.assertIn("DEMO DATA", meta_rec.get("provenance", ""))

            # Test incident service rejection
            svc = IncidentService()
            demo_summary = {
                "analysis_id": "test_demo_run_999",
                "status": "COMPLETED",
                "processing_mode": "DEMO",
                "data_source": "DEMO_SYNTHETIC",
                "is_demo_data": True,
                "location": {"latitude": 15.0, "longitude": 75.0},
                "change_stats": {
                    "deforested": {"hectares": 50.0, "percentage": 15.0},
                    "mean_delta_ndvi": -0.35,
                    "total_valid_pixels": 1000
                }
            }
            inc, err = svc.register_analysis(demo_summary)
            self.assertIsNone(inc)
            self.assertIn("Demo or simulated analyses cannot generate genuine incidents", err)

    def test_fix2_invalid_and_masked_pixels_produce_nan_ndvi(self):
        """Fix 2: Masked pixels (-9999.0), zero/negative reflectance, and near-zero denominators produce np.nan."""
        red = np.array([
            [0.10, -9999.0, 0.00],   # Valid, masked default, zero reflectance
            [0.20, 0.05,    2.50]    # Valid, valid, invalid reflectance > 2.0
        ], dtype=np.float32)
        nir = np.array([
            [0.50, -9999.0, 0.00],   # Valid, masked default, zero reflectance
            [0.60, 0.05001, 0.80]    # Valid, valid near-zero denom, invalid reflectance
        ], dtype=np.float32)

        ndvi = Anni_code.calculate_ndvi(red, nir)

        # (0, 0) is valid: (0.5 - 0.1) / (0.5 + 0.1) = 0.4 / 0.6 = 0.6667
        self.assertAlmostEqual(ndvi[0, 0], 2.0 / 3.0, places=4)
        # (0, 1) is masked defaultValue=-9999.0 -> np.nan
        self.assertTrue(np.isnan(ndvi[0, 1]))
        # (0, 2) is zero reflectance -> np.nan
        self.assertTrue(np.isnan(ndvi[0, 2]))
        # (1, 0) is valid: (0.6 - 0.2) / (0.6 + 0.2) = 0.4 / 0.8 = 0.50
        self.assertAlmostEqual(ndvi[1, 0], 0.50, places=4)
        # (1, 2) has red > 2.0 -> np.nan
        self.assertTrue(np.isnan(ndvi[1, 2]))

    def test_fix2_comparison_mask_and_consistent_denominators(self):
        """Fix 2: Change statistics are computed strictly over comparison_mask (valid in BOTH epochs), and percentages sum to 100%."""
        # 4 pixels:
        # P0: Valid forest in base (0.7), cleared in recent (0.1) -> Deforested
        # P1: Cloud in baseline (np.nan), valid in recent (0.5) -> Masked in comparison!
        # P2: Valid in base (0.6), cloud in recent (np.nan) -> Masked in comparison!
        # P3: Valid stable forest in both (0.7, 0.72) -> Stable Dense
        ndvi_base = np.array([[0.70, np.nan], [0.60, 0.70]], dtype=np.float32)
        ndvi_rec  = np.array([[0.10, 0.50],   [np.nan, 0.72]], dtype=np.float32)

        meta = {"scale_meters": 20}
        change_map, delta_ndvi, stats = Anni_code.detect_deforestation(ndvi_base, ndvi_rec, meta, meta)

        # Total pixels is 4, but only 2 pixels (P0 and P3) are valid in BOTH epochs
        self.assertEqual(stats["total_pixels"], 4)
        self.assertEqual(stats["total_valid_pixels"], 2)
        self.assertEqual(stats["masked_pixels"], 2)
        self.assertEqual(stats["valid_data_pct"], 50.0)

        # P0 is deforested, P3 is stable dense
        self.assertEqual(stats["deforested"]["pixels"], 1)
        self.assertEqual(stats["stable_dense"]["pixels"], 1)
        self.assertEqual(stats["regrowth"]["pixels"], 0)
        self.assertEqual(stats["stable_light"]["pixels"], 0)
        self.assertEqual(stats["non_forest"]["pixels"], 0)

        # Denominator check: 1/2 = 50% deforested, 1/2 = 50% stable dense
        self.assertEqual(stats["deforested"]["percentage"], 50.0)
        self.assertEqual(stats["stable_dense"]["percentage"], 50.0)
        total_pct = (stats["deforested"]["percentage"] + stats["stable_dense"]["percentage"] +
                     stats["stable_light"]["percentage"] + stats["regrowth"]["percentage"] +
                     stats["non_forest"]["percentage"])
        self.assertAlmostEqual(total_pct, 100.0, places=2)

        # Invalid pixels in change_map must be marked 255
        self.assertEqual(change_map[0, 1], 255)
        self.assertEqual(change_map[1, 0], 255)
        self.assertTrue(np.isnan(delta_ndvi[0, 1]))
        self.assertTrue(np.isnan(delta_ndvi[1, 0]))

    def test_fix3_provenance_and_failed_analyses_rejected(self):
        """Fix 3: Provenance metadata is recorded, and failed or data-unavailable runs are not treated as valid detections."""
        svc = IncidentService()
        failed_summary = {
            "analysis_id": "failed_run_01",
            "status": "FAILED",
            "processing_mode": "REAL",
            "is_demo_data": False,
            "location": {"latitude": 15.0, "longitude": 75.0}
        }
        inc, err = svc.register_analysis(failed_summary)
        self.assertIsNone(inc)
        self.assertIn("Only successfully completed analyses", err)

    def test_sample_rectangle_to_float_conversion(self):
        """Verify that bands are cast to float before calling sampleRectangle with defaultValue=-9999.0"""
        mock_col = MagicMock()
        mock_col.filterBounds.return_value = mock_col
        mock_col.filterDate.return_value = mock_col
        mock_col.filter.return_value = mock_col
        mock_col.sort.return_value = mock_col
        mock_col.size.return_value.getInfo.return_value = 1

        mock_img = MagicMock()
        mock_col.first.return_value = mock_img
        mock_img.get.side_effect = lambda prop: MagicMock(getInfo=lambda: "dummy_val" if prop == "system:index" else 1672531200000 if prop == "system:time_start" else 0.0)

        mock_selected = MagicMock()
        mock_img.select.return_value = mock_selected

        mock_float1 = MagicMock()
        mock_selected.toFloat.return_value = mock_float1

        mock_mult = MagicMock()
        mock_float1.multiply.return_value = mock_mult

        mock_reproject = MagicMock()
        mock_mult.reproject.return_value = mock_reproject

        mock_float2 = MagicMock()
        mock_reproject.toFloat.return_value = mock_float2

        mock_sampled = MagicMock()
        mock_float2.sampleRectangle.return_value = mock_sampled

        # Return mock arrays
        mock_b4_info = [[0.1, 0.2], [0.1, 0.2]]
        mock_b8_info = [[0.5, 0.6], [0.5, 0.6]]
        b4_m = MagicMock()
        b4_m.getInfo.return_value = mock_b4_info
        b8_m = MagicMock()
        b8_m.getInfo.return_value = mock_b8_info
        mock_sampled.get.side_effect = lambda band: b4_m if band == 'B4' else b8_m

        with patch('ee.ImageCollection', return_value=mock_col), \
             patch('ee.Geometry.Point'), \
             patch('ee.Filter.lt'), \
             patch('ee.Date'):
            b4, b8, meta = gee_data_loader.fetch_sentinel2_bands(
                lat=15.0, lon=75.0,
                start_date="2023-01-01", end_date="2023-05-31",
                use_scl_mask=False
            )

            # Assert .toFloat() was called on selected bands
            mock_selected.toFloat.assert_called_once()
            # Assert sampleRectangle was called with defaultValue=-9999.0
            mock_float2.sampleRectangle.assert_called_once()
            args, kwargs = mock_float2.sampleRectangle.call_args
            self.assertEqual(kwargs.get("defaultValue"), -9999.0)
            self.assertEqual(b4.shape, (2, 2))
            self.assertEqual(b8.shape, (2, 2))

if __name__ == "__main__":
    unittest.main()
