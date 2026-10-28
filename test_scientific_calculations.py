import unittest
import numpy as np
import Anni_code

class TestScientificCalculations(unittest.TestCase):

    def test_ndvi_standard(self):
        # Red = 0.1, NIR = 0.5 -> NDVI = (0.5 - 0.1) / (0.5 + 0.1) = 0.4 / 0.6 = 0.6667
        red = np.array([[0.1, 0.2], [0.05, 0.3]], dtype=np.float32)
        nir = np.array([[0.5, 0.2], [0.85, 0.1]], dtype=np.float32)
        ndvi = Anni_code.calculate_ndvi(red, nir)

        self.assertAlmostEqual(ndvi[0, 0], (0.5 - 0.1) / (0.5 + 0.1), places=4)
        self.assertAlmostEqual(ndvi[0, 1], 0.0, places=4)
        self.assertTrue(np.all(ndvi >= -1.0) and np.all(ndvi <= 1.0))

    def test_ndvi_zero_denominator_and_invalid(self):
        # Red = 0, NIR = 0 -> invalid reflectance and near-zero denominator -> must be np.nan
        red = np.array([[0.0, 0.0]], dtype=np.float32)
        nir = np.array([[0.0, 0.0]], dtype=np.float32)
        ndvi = Anni_code.calculate_ndvi(red, nir)
        self.assertTrue(np.isnan(ndvi[0, 0]))
        self.assertTrue(np.isnan(ndvi[0, 1]))

    def test_classification_thresholds(self):
        # 0.6 = dense, 0.35 = light, 0.1 = non-forest
        ndvi = np.array([[0.70, 0.35], [0.10, 0.50]], dtype=np.float32)
        class_map, stats = Anni_code.classify_single_epoch(ndvi)

        self.assertEqual(stats["total_pixels"], 4)
        self.assertEqual(stats["dense_pixels"], 2)       # 0.70 and 0.50
        self.assertEqual(stats["light_pixels"], 1)       # 0.35
        self.assertEqual(stats["non_forest_pixels"], 1)  # 0.10
        self.assertEqual(stats["dense_pct"], 50.0)
        self.assertEqual(stats["light_pct"], 25.0)
        self.assertEqual(stats["non_forest_pct"], 25.0)

    def test_deforestation_detection(self):
        # Baseline: was forest (0.65), Recent: canopy cleared (0.15) -> Drop = -0.50 (Deforested)
        ndvi_base = np.array([[0.65, 0.60]], dtype=np.float32)
        ndvi_rec = np.array([[0.15, 0.62]], dtype=np.float32)

        meta_base = {"scale_meters": 20}
        meta_rec = {"scale_meters": 20}

        change_map, delta_ndvi, change_stats = Anni_code.detect_deforestation(
            ndvi_base, ndvi_rec, meta_base, meta_rec
        )

        self.assertEqual(change_stats["deforested"]["pixels"], 1)
        self.assertEqual(change_stats["stable_dense"]["pixels"], 1)
        self.assertAlmostEqual(delta_ndvi[0, 0], -0.50, places=3)
        self.assertAlmostEqual(delta_ndvi[0, 1], +0.02, places=3)

    def test_area_hectares_calculation(self):
        # 100 pixels at 20m resolution = 100 * (20*20) m2 = 40,000 m2 = 4.0 hectares
        scale = 20
        pixels = 100
        ha = (pixels * scale * scale) / 10000.0
        km2 = ha / 100.0
        self.assertEqual(ha, 4.0)
        self.assertEqual(km2, 0.04)

if __name__ == "__main__":
    unittest.main()
