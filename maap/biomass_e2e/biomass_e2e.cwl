cwlVersion: v1.2
class: CommandLineTool
label: rift-biomass-e2e

# Reference CWL for local cwltool runs / parity. On MAAP the process CWL is generated from
# algorithm_config.yml at registration; DPS invokes run.sh (which activates the conda envs).
baseCommand:
  - /opt/app/rift/maap/biomass_e2e/run.sh

requirements:
  NetworkAccess:
    networkAccess: true

inputs:
  item_id:
    type: string
    inputBinding: { prefix: --item_id }
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
  gate_thresh:
    type: string
    default: "0.65"
    inputBinding: { prefix: --gate_thresh }
  edge_margin:
    type: string
    default: "0"
    inputBinding: { prefix: --edge_margin }

outputs:
  out:
    type: Directory
    outputBinding:
      glob: output
