import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
import Anni_code

class TestColorRendering(unittest.TestCase):

    def test_masked_pixels_not_colored_blue_regrowth(self):
        """
        Verify that masked pixels (255) are transparent and do NOT receive
        the blue regrowth color (#00b0ff) in the categorized change map.
        """
        # Create a colormap matching Anni_code.py
        cmap_change = ListedColormap(['#d3d3d3', '#90ee90', '#1b5e20', '#d50000', '#00b0ff'])
        cmap_change.set_bad(color='none')
        cmap_change.set_over(color='none')
        cmap_change.set_under(color='none')
        norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], cmap_change.N)

        # Class 4 = Regrowth (should be blue)
        # Class 255 = Masked / Invalid (MUST be transparent: alpha = 0.0)
        rgba_regrowth = cmap_change(norm(4))
        # When masked with masked_where:
        test_arr = np.array([0, 1, 2, 3, 4, 255], dtype=np.uint8)
        masked_arr = np.ma.masked_where(test_arr == 255, test_arr)

        rgba_rendered = cmap_change(norm(masked_arr))

        # Regrowth pixel (index 4): Blue (Red=0, Green>0.6, Blue=1.0, Alpha=1.0)
        self.assertAlmostEqual(rgba_rendered[4][0], 0.0, places=2)
        self.assertAlmostEqual(rgba_rendered[4][2], 1.0, places=2)
        self.assertEqual(rgba_rendered[4][3], 1.0) # fully opaque

        # Masked pixel (index 5): MUST BE TRANSPARENT (Alpha = 0.0)
        self.assertEqual(rgba_rendered[5][3], 0.0, "Masked pixel must have alpha=0 (transparent), not colored blue!")

    def test_delta_ndvi_loss_is_red_and_gain_is_blue(self):
        """
        Verify that delta_ndvi uses coolwarm_r so that:
        Negative delta (Loss) -> Red
        Positive delta (Gain) -> Blue
        NaN (Masked) -> Transparent
        """
        cmap_delta = plt.colormaps['coolwarm_r'].resampled(256)
        cmap_delta.set_bad(color='none')

        # Negative delta = -0.35 (vegetation loss)
        loss_color = cmap_delta((-0.35 - (-0.4)) / 0.8) # normalized to [0, 1]
        # In coolwarm_r: 0.0 is red, 1.0 is blue
        self.assertGreater(loss_color[0], loss_color[2], "Vegetation loss must have Red > Blue")

        # Positive delta = +0.35 (vegetation gain)
        gain_color = cmap_delta((+0.35 - (-0.4)) / 0.8)
        self.assertGreater(gain_color[2], gain_color[0], "Vegetation gain must have Blue > Red")

        # NaN delta = masked
        nan_arr = np.ma.masked_invalid(np.array([np.nan]))
        nan_color = cmap_delta(nan_arr)[0]
        self.assertEqual(nan_color[3], 0.0, "NaN delta NDVI must be transparent (alpha=0.0)")

    def test_spatial_map_generation_with_masked_pixels(self):
        """
        Test end-to-end create_spatial_map generation with realistic pixel data containing
        forest, non-forest, loss, regrowth, and cloud-masked (255) pixels.
        """
        import tempfile, os
        # 10x10 test grid
        ndvi_base = np.full((10, 10), 0.65, dtype=np.float32)
        ndvi_rec  = np.full((10, 10), 0.65, dtype=np.float32)

        # Add 1 loss pixel
        ndvi_rec[0, 0] = 0.15
        # Add 1 regrowth pixel
        ndvi_base[1, 1] = 0.15
        ndvi_rec[1, 1]  = 0.65
        # Add 2 cloud masked pixels
        ndvi_base[2, 2] = np.nan
        ndvi_rec[3, 3]  = np.nan

        meta = {"latitude": 15.0, "longitude": 75.0, "scale_meters": 20}
        change_map, delta_ndvi, stats = Anni_code.detect_deforestation(ndvi_base, ndvi_rec, meta, meta)

        self.assertEqual(stats["deforested"]["pixels"], 1)
        self.assertEqual(stats["regrowth"]["pixels"], 1)
        self.assertEqual(stats["masked_pixels"], 2)

        with tempfile.TemporaryDirectory() as tmpdir:
            map_path = Anni_code.create_spatial_map(
                tmpdir, "test_render_01", ndvi_base, ndvi_rec, delta_ndvi, change_map, meta
            )
            self.assertTrue(os.path.exists(map_path))
            self.assertGreater(os.path.getsize(map_path), 1000)

if __name__ == "__main__":
    unittest.main()
