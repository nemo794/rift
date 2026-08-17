# Installation Instructions

## Prerequisites

- **Conda** or **Mamba** (recommended for faster installs)
- **Git**
- **Python 3.11** (will be installed via conda)

## Step-by-Step Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/biomass-geocode.git
cd biomass-geocode
```

### 2. Create Conda Environment

Using conda:
```bash
conda env create -f environment.yaml
```

Or using mamba (faster):
```bash
mamba env create -f environment.yaml
```

This creates a conda environment named `biomass_processing` with all dependencies except `biomass-reader`.

### 3. Activate the Environment

```bash
conda activate biomass_processing
```

### 4. Install biomass-reader

The `biomass-reader` package is not available on conda and must be installed from GitHub:

```bash
# Clone the repository
git clone https://github.com/scottstanie/biomass-reader.git
cd biomass-reader

# Install with ionosphere support
pip install -e '.[ionosphere]'

cd ..
```

**Optional: Fix for high-latitude coarse resolution**

If processing high-latitude BIOMASS data where range resolution is coarse (>40m), use the fix-native-posting branch:

```bash
cd biomass-reader
git checkout fix-native-posting-coarse-resolution
pip install -e '.[ionosphere]'
cd ..
```

### 5. Verify Installation

Run the test suite:

```bash
python tests/test_grid_system.py
```

Expected output:
```
======================================================================
ANTARCTICA MASTER GRID - COMPREHENSIVE TEST SUITE
======================================================================
...
✓✓✓ ALL TESTS PASSED ✓✓✓
The Antarctica master grid system is working correctly!
```

If all tests pass, installation is complete!

## Troubleshooting

### isce3 Installation Issues

If isce3 fails to install via conda:

1. Try using mamba instead of conda (faster and more reliable):
   ```bash
   mamba install -c conda-forge isce3
   ```

2. Check your platform is supported (osx-arm64, osx-64, linux-64)

3. Try installing from a different channel:
   ```bash
   conda install -c conda-forge -c defaults isce3
   ```

### GDAL/NetCDF Issues

If you see errors about NetCDF when reading ionosphere LUT files:

```bash
conda install -c conda-forge libgdal-netcdf
```

### biomass-reader Not Found

If Python can't find the `biomass_reader` module:

1. Make sure you're in the `biomass_processing` conda environment:
   ```bash
   conda activate biomass_processing
   ```

2. Verify biomass-reader is installed:
   ```bash
   pip list | grep biomass
   ```

3. Check the installation path:
   ```bash
   python -c "import biomass_reader; print(biomass_reader.__file__)"
   ```

## Updating

To update the package:

```bash
cd biomass-geocode
git pull

# Update conda environment if dependencies changed
conda env update -f environment.yaml --prune

# Update biomass-reader
cd ../biomass-reader
git pull
pip install -e '.[ionosphere]'
```

## Uninstalling

To completely remove the environment:

```bash
conda deactivate
conda env remove -n biomass_processing
```

## Alternative Installation (pip only)

If you prefer not to use conda, you can install with pip, but you'll need to:

1. Install Python 3.11
2. Install GDAL and isce3 system-wide (complex, not recommended)
3. Install Python packages:
   ```bash
   pip install numpy rasterio scipy lxml netcdf4 xarray python-dateutil requests
   pip install sardem
   pip install -e ./biomass-reader[ionosphere]
   ```

**Note:** Installing isce3 without conda is difficult. We strongly recommend using the conda environment.

## Platform-Specific Notes

### macOS Apple Silicon (M1/M2/M3)

- Use the `osx-arm64` platform
- isce3 runs natively on Apple Silicon (no Rosetta needed)
- May need to install Xcode Command Line Tools:
  ```bash
  xcode-select --install
  ```

### macOS Intel

- Use the `osx-64` platform
- Should work out of the box

### Linux

- Use the `linux-64` platform
- May need system libraries for GDAL:
  ```bash
  sudo apt-get install libgdal-dev  # Debian/Ubuntu
  sudo yum install gdal-devel       # RedHat/CentOS
  ```

## Next Steps

After successful installation, see:

- [README.md](README.md) for quick start guide
- [docs/GRID_SYSTEM.md](docs/GRID_SYSTEM.md) for grid system documentation
- [docs/API.md](docs/API.md) for API reference
- [examples/](examples/) for example workflows
