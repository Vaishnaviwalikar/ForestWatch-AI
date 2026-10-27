import numpy as np
import cv2
import matplotlib.pyplot as plt

def load_png_image(image_path):
    image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("Image not loaded. Check file path!")
    
    print("✅ Image Loaded Successfully")
    print("Image Shape:", image.shape)
    print("Unique Pixel Values:", np.unique(image))
    
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image.astype(np.float32) / 255.0

def compute_ndvi(nir_band, red_band):
    ndvi = (nir_band - red_band) / (nir_band + red_band + 1e-10)
    return ndvi

def detect_deforestation(ndvi, threshold=0.2):
    return ndvi < threshold

def visualize_results(ndvi, deforestation_mask):
    print(f"NDVI Range: Min = {ndvi.min()}, Max = {ndvi.max()}, Mean = {ndvi.mean()}")
    
    fig, ax = plt.subplots(1, 3, figsize=(15, 5))
    
    ax[0].imshow(ndvi, cmap='RdYlGn', vmin=ndvi.min(), vmax=ndvi.max())
    ax[0].set_title("NDVI Index")
    ax[0].axis("off")
    
    ax[1].imshow(deforestation_mask, cmap='gray')
    ax[1].set_title("Deforestation Detection")
    ax[1].axis("off")
    
    ax[2].hist(ndvi.ravel(), bins=50, color='green', alpha=0.7)
    ax[2].set_title("NDVI Histogram")
    
    plt.show()

def save_results(ndvi, deforestation_mask, output_file="deforestation_report.txt"):
    with open(output_file, "w") as f:
        f.write("NDVI Statistics:\n")
        f.write(f"Min: {ndvi.min()}, Max: {ndvi.max()}, Mean: {ndvi.mean()}\n")
        f.write(f"Deforested Pixels: {deforestation_mask.sum()}\n")
        f.write(f"Percentage Deforested: {(deforestation_mask.sum() / deforestation_mask.size) * 100:.2f}%\n")
    print(f"Report saved: {output_file}")
    
    cv2.imwrite("ndvi_output.png", (ndvi * 255).astype(np.uint8))
    print("✅ NDVI Image saved as ndvi_output.png")

if __name__ == "__main__":
    image_path = "sentinel_image.png"
    image = load_png_image(image_path)
    
    nir_band = image[:, :, 2]  # Try swapping if incorrect
    red_band = image[:, :, 0]
    
    ndvi = compute_ndvi(nir_band, red_band)
    deforestation_mask = detect_deforestation(ndvi)
    
    visualize_results(ndvi, deforestation_mask)
    save_results(ndvi, deforestation_mask)
