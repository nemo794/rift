cwlVersion: v1.2
class: CommandLineTool
label: rift-biomass2cog

# Reference CWL for local cwltool runs / parity. On MAAP the process CWL is generated from
# algorithm_config.yml at registration; DPS invokes run.sh (which activates the conda env).
baseCommand:
  - /opt/app/rift/maap/biomass2cog/run.sh

requirements:
  NetworkAccess:
    networkAccess: true

inputs:
  item_id:
    type: string
    inputBinding: { prefix: --item_id }
  pols:
    type: string
    default: "HH,HV,VH,VV"
    inputBinding: { prefix: --pols }
  amp_only:
    type: string
    default: "false"
    inputBinding: { prefix: --amp_only }

outputs:
  out:
    type: Directory
    outputBinding:
      glob: output
