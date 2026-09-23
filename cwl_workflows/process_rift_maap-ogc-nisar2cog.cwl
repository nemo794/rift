cwlVersion: v1.2
$graph:
- class: Workflow
  label: rift-nisar2cog
  doc: 'NISAR L2 GSLC to per-polarization amplitude (and phase) Cloud-Optimized GeoTIFFs
    on the Antarctica master grid (EPSG:3031, 512x512 chunks). Frequency-A complex
    samples are masked in the complex domain and placed losslessly (no resampling).
    No inference is run.

    '
  id: rift-nisar2cog
  inputs:
    gslc_url:
      doc: HTTPS or S3 URL to a NISAR L2 GSLC .h5 granule. Downloaded into ./input
        at runtime.
      label: NISAR GSLC URL
      type: string
    pols:
      doc: Comma-separated polarizations (e.g. HH,HV). Empty means all frequency-A
        pols.
      label: Polarizations
      type: string?
      default: ''
    amp_only:
      doc: true|false. When true, skip the per-pol phase COGs and write amplitude
        only.
      label: Amplitude only
      type: string?
      default: 'false'
  outputs:
    out:
      type: Directory
      outputSource: process/outputs_result
  steps:
    process:
      run: '#main'
      in:
        gslc_url: gslc_url
        pols: pols
        amp_only: amp_only
      out:
      - outputs_result
- class: CommandLineTool
  id: main
  requirements:
    DockerRequirement:
      dockerPull: ghcr.io/nemo794/rift:maap-ogc-nisar2cog
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      ramMin: 6000
      coresMin: 2
      outdirMax: 20000
  baseCommand: run.py
  inputs:
    gslc_url:
      type: string
      inputBinding:
        position: 1
        prefix: --gslc_url
    pols:
      type: string?
      inputBinding:
        position: 2
        prefix: --pols
      default: ''
    amp_only:
      type: string?
      inputBinding:
        position: 3
        prefix: --amp_only
      default: 'false'
  outputs:
    outputs_result:
      outputBinding:
        glob: ./output*
      type: Directory
s:author:
- class: s:Person
  s:name: Samantha C. Niemoeller
s:contributor:
- class: s:Person
  s:name: Samantha C. Niemoeller
s:citation: https://github.com/nemo794/rift.git
s:codeRepository: https://github.com/nemo794/rift.git
s:commitHash: a7ab5cb5449838c693633dedde097f782424cbc6
s:dateCreated: 2026-09-23
s:license: https://raw.githubusercontent.com/nemo794/rift/main/LICENSE-BSD-3-Clause.txt
s:softwareVersion: 1.0.0
s:version: main
s:releaseNotes: Initial OGC application package for the nisar2cog workflow.
s:keywords: nisar, gslc, sar, cog, antarctica
$namespaces:
  s: https://schema.org/
$schemas:
- https://raw.githubusercontent.com/schemaorg/schemaorg/refs/heads/main/data/releases/9.0/schemaorg-current-http.rdf
