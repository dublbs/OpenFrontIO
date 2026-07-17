#!/usr/bin/env python3
"""
Convert any terrain photo/screenshot into OpenFront.io map format.

Automatically detects water (blue areas) and maps terrain colors to elevation:
  - Dark green  -> low elevation (plains)
  - Light green -> mid elevation (hills)
  - White/bright -> high elevation (mountains)

Usage:
    python3 convert_photo.py input.jpg output.png
    python3 convert_photo.py input.jpg output.png --water-threshold 0.15
"""

import sys
import argparse
import numpy as np
from PIL import Image


def classify_pixels(arr):
    """
    Classify each pixel as water or land based on color.
    Returns (water_mask, land_mask).
    """
    r, g, b = arr[:,:,0].astype(float), arr[:,:,1].astype(float), arr[:,:,2].astype(float)

    # Water detection: blue-dominant and sufficiently blue
    # Blue dominance: B significantly higher than R
    blue_dominant = (b - r) > 20

    # Blue absolute: B channel above threshold
    blue_absolute = b > 150

    # Also detect very dark pixels as water (deep ocean)
    dark = (r + g + b) < 100

    water_mask = (blue_dominant & blue_absolute) | dark

    # Land: everything else
    land_mask = ~water_mask

    return water_mask, land_mask


def elevation_from_color(arr, land_mask):
    """
    Map land colors to elevation (0-60).

    Strategy: use luminance (brightness) as primary elevation indicator.
    - Darker pixels = lower elevation (valleys, plains)
    - Brighter pixels = higher elevation (mountains, snow)

    Also factor in green channel: more green = lower elevation.
    """
    r = arr[land_mask, 0].astype(float)
    g = arr[land_mask, 1].astype(float)
    b = arr[land_mask, 2].astype(float)

    # Luminance (perceived brightness)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b

    # Green ratio: how green is this pixel relative to total brightness?
    # Higher green ratio = lower elevation
    green_ratio = g / (luminance + 1)

    # Combine: bright + less green = high elevation
    # Normalize luminance to 0-1
    lum_norm = np.clip((luminance - 80) / (255 - 80), 0, 1)

    # Invert green ratio: less green -> higher
    green_inv = np.clip(1.0 - green_ratio * 1.5, 0, 1)

    # Weighted combination: 70% brightness, 30% green-inverse
    elev_score = 0.7 * lum_norm + 0.3 * green_inv

    # Map to 0-60 elevation range
    elevation = elev_score * 60

    return np.clip(elevation, 0, 60).astype(np.uint8)


def convert_to_openfront(input_path, output_path, water_threshold=None):
    """Convert a photo to OpenFront terrain PNG format."""
    img = Image.open(input_path).convert("RGBA")
    arr = np.array(img)

    print(f"Input: {input_path} ({arr.shape[1]}x{arr.shape[0]})")

    # Classify pixels
    water_mask, land_mask = classify_pixels(arr)

    water_pct = 100 * water_mask.sum() / (arr.shape[0] * arr.shape[1])
    land_pct = 100 * land_mask.sum() / (arr.shape[0] * arr.shape[1])
    print(f"  Water: {water_pct:.1f}%  |  Land: {land_pct:.1f}%")

    # Compute elevation for land pixels
    elevation = elevation_from_color(arr, land_mask)

    # Build output array (transparent by default)
    out = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)

    # Fill land pixels with OpenFront color encoding
    land_indices = np.where(land_mask)

    # B channel = 140 + elevation (elevation 0-60 -> B 140-200)
    b_val = np.clip(140 + elevation, 140, 200).astype(np.uint8)

    # R, G channels: brownish-green tones that vary with elevation
    # Low elevation: greener (R~160, G~180)
    # High elevation: browner/grayer (R~190, G~170)
    r_val = np.clip(160 + elevation * 0.5, 160, 200).astype(np.uint8)
    g_val = np.clip(180 - elevation * 0.2, 160, 190).astype(np.uint8)

    out[land_indices[0], land_indices[1], 0] = r_val
    out[land_indices[0], land_indices[1], 1] = g_val
    out[land_indices[0], land_indices[1], 2] = b_val
    out[land_indices[0], land_indices[1], 3] = 255

    # Water stays transparent (already 0,0,0,0)

    # Save
    result = Image.fromarray(out, "RGBA")
    result.save(output_path, "PNG")
    print(f"  Saved: {output_path}")

    # Verify
    verify = np.array(result)
    land_b = verify[verify[:,:,3] >= 20, 2]
    if len(land_b) > 0:
        print(f"  Land B range: {land_b.min()}-{land_b.max()} (target: 140-200)")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert terrain photo to OpenFront.io map format"
    )
    parser.add_argument("input", help="Input image path (JPG, PNG, etc.)")
    parser.add_argument("output", help="Output PNG path")
    parser.add_argument("--water-threshold", type=float, default=None,
                        help="Override water detection threshold")
    args = parser.parse_args()

    convert_to_openfront(args.input, args.output, args.water_threshold)


if __name__ == "__main__":
    main()
