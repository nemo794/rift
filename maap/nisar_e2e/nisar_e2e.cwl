cwlVersion: v1.2
class: CommandLineTool
label: rift-nisar-e2e

# Reference CWL for local cwltool runs / parity. On MAAP the process CWL is generated from
# algorithm_config.yml at registration; DPS invokes run.sh (which activates the conda envs).
baseCommand:
  - /opt/app/rift/maap/nisar_e2e/run.sh

requirements:
  NetworkAccess:
    networkAccess: true

inputs:
  access_mode:
    type: string
    default: auto
    inputBinding: { prefix: --access_mode }
  s3_href:
    type: string?
    inputBinding: { prefix: --s3_href }
  https_href:
    type: string?
    inputBinding: { prefix: --https_href }
  short_name:
    type: string
    default: NISAR_L2_GSLC_PROVISIONAL_V1
    inputBinding: { prefix: --short_name }
  granule_index:
    type: string
    default: "0"
    inputBinding: { prefix: --granule_index }
  asf_s3_creds_url:
    type: string
    default: "https://nisar.asf.earthdatacloud.nasa.gov/s3credentials"
    inputBinding: { prefix: --asf_s3_creds_url }
  pols:
    type: string?
    inputBinding: { prefix: --pols }
  amp_only:
    type: string
    default: "false"
    inputBinding: { prefix: --amp_only }
  max_tiles:
    type: string?
    inputBinding: { prefix: --max_tiles }
  crop_to_scanned:
    type: string
    default: "false"
    inputBinding: { prefix: --crop_to_scanned }

outputs:
  out:
    type: Directory
    outputBinding:
      glob: output
