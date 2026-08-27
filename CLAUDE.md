# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ComfyUI-Image-Saver is a ComfyUI custom node plugin that saves images with generation metadata compatible with Civitai. It supports PNG, JPEG, and WebP formats, storing model, LoRA, and embedding hashes for proper resource recognition.

## Development Commands

### Testing
```bash
cd saver && python -m pytest
cd tests && python -m pytest
```
See "Testing" below for what each suite covers.

### Installation for Development
```bash
pip install -r requirements.txt
```

### Package Information
- Main dependency: `piexif` (for EXIF metadata handling)
- Version defined in `pyproject.toml`
- ComfyUI plugin structure with node registration

## Architecture

### Core Components

1. **Node Registration (`__init__.py`)**
   - Registers all custom nodes with ComfyUI
   - Maps node class names to implementations
   - Defines `WEB_DIRECTORY` for JavaScript assets

2. **Core Image Saving Nodes (`nodes.py`)**
   - `ImageSaver`: Main node for saving images with full metadata
   - `ImageSaverSimple`: Simplified version for basic usage
   - `ImageSaverMetadata`: Metadata-only node for separation of concerns
   - `Metadata` dataclass: Structured metadata container

3. **Pipe Integration Nodes (`nodes_pipe.py`)**
   - `MakeImageSaverSimpleConfig`, `MakeImageSaverMetadataConfig`: Standalone configurations.
   - `MakeImageSaverPipe`: Bundles configs into a single connection.
   - `EditImageSaverPipe`, `ReadImageSaverPipe`: Dynamic modification and extraction of pipe data.
   - `ImageSaverFromPipe`: Resolves the deferred pipe data and performs the save operation.

4. **Core Saver Logic (`saver/saver.py`)**
   - `save_image()`: Handles different image formats (PNG, JPEG, WebP)
   - PNG: Uses `PngInfo` for metadata storage
   - JPEG/WebP: Uses EXIF format via `piexif`
   - Workflow embedding with size limits (65535 bytes for JPEG)

5. **Utility Modules**
   - `utils.py`: File operations, hashing, path resolution
   - `utils_civitai.py`: Civitai API integration and metadata formatting
   - `prompt_metadata_extractor.py`: Extracts LoRAs and embeddings from prompts

6. **Other Specialized Nodes**
   - `nodes_loaders.py`: Checkpoint and UNet loaders with name tracking
   - `nodes_selectors.py`: Sampler and scheduler selection utilities
   - `nodes_literals.py`: Literal value generators (seed, strings, etc.)
   - `civitai_nodes.py`: Civitai hash fetching functionality
   - `random_tag_picker.py`: Random prompt tagging utility

### Key Features

- **Metadata Support**: A1111-compatible parameters with Civitai resource hashes
- **Multi-format**: PNG (full workflow), JPEG/WebP (parameters only)
- **Hash Calculation**: SHA256 hashing with file caching (`.sha256` files)
- **Resource Detection**: Automatic LoRA, embedding, and model hash extraction
- **Civitai Integration**: Downloads resource metadata for proper attribution
- **Filename Templating**: Supports variables like `%date`, `%time`, `%seed`, `%model`, `%width`, `%height`, `%counter` (including zero-padded format via `%counter<padding>`), `%sampler_name`, `%steps`, `%cfg`, `%scheduler_name`, `%basemodelname`, `%denoise`, `%clip_skip`, `%custom`

### Advanced Features

- **Multiple Model Support**: ModelName parameter accepts comma-separated model names. Primary model hash is used in metadata, additional models are added to `additional_hashes`
- **Easy Remix Mode**: When enabled, automatically cleans prompts by removing LoRA tags and simplifying embeddings for better Civitai remix compatibility
- **Custom Metadata Field**: Arbitrary string can be inserted into A1111 parameters via the `custom` parameter
- **Manual Hash Management**: User-added resource hashes stored in `/models/image-saver/manual-hashes.json` for resources not found via Civitai API
- **File Path Matching**: Three-level fallback strategy for finding resources:
  1. Exact path match
  2. Filename stem match (without extension)
  3. Base name match (case-insensitive)
- **Civitai Hash Fetcher Node**: Dedicated node (`CivitaiHashFetcher`) for looking up model hashes directly from Civitai by username and model name
- **Caching Strategy**:
  - `.sha256` files: SHA256 hashes cached alongside model files
  - `.civitai.info` files: Civitai metadata cached to reduce API calls
  - Internal cache: CivitaiHashFetcher maintains runtime cache to avoid redundant lookups

### Data Flow

1. **Input Processing**: Parameters and images received from ComfyUI workflow
2. **Metadata Extraction**: Prompts parsed for LoRAs, embeddings, model references
3. **Hash Generation**: SHA256 hashes calculated for all resources
4. **Civitai Lookup**: Resource metadata fetched from Civitai API
5. **Metadata Assembly**: A1111-compatible parameter string generated
6. **Image Saving**: Metadata embedded in image files based on format
7. **Output**: Saved images with proper metadata for sharing/recognition

### File Structure

```
ComfyUI-Image-Saver/
├── __init__.py              # Node registration
├── nodes.py                 # Main image saver nodes
├── saver/                   # Core saving logic
│   ├── saver.py            # Image format handling
│   └── test_saver.py       # Unit tests
├── utils.py                 # File operations and hashing
├── utils_civitai.py         # Civitai API integration
├── prompt_metadata_extractor.py  # Prompt parsing
├── nodes_*.py               # Specialized node types
├── civitai_nodes.py         # Civitai functionality
└── js/                      # Frontend JavaScript
    ├── read_exif_workflow.js  # ComfyUI extension for reading EXIF workflows from dropped images
    └── lib/exif-reader.js   # EXIF reading utilities (ExifReader v4.26.2)
```

## Testing

Tests are split into two independent suites, each with its own `pytest.ini`, because `saver/saver.py` has no ComfyUI dependency while `nodes.py`/`utils.py` do:

- `saver/test_saver.py` — image format/metadata writing (`save_image`), no ComfyUI dependency. Run with `cd saver && python -m pytest`.
- `tests/test_paths.py` — output-path/filename containment (`resolve_within_output`, `ImageSaver.save_images`). `tests/conftest.py` stubs ComfyUI's runtime modules to import `nodes.py`/`utils.py` outside ComfyUI. Run with `cd tests && python -m pytest`.

## Important Notes

- Hash files (`.sha256`) are cached alongside model files to avoid recalculation
- JPEG format has a 65535-byte limit for EXIF data
- WebP workflow embedding is experimental
- Resource paths are resolved through ComfyUI's folder_paths system
- Civitai integration can be disabled via `download_civitai_data` parameter