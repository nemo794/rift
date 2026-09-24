# Built on MAAP's maap_base image, which lives in the private mas.maap-project.org
# registry (only MAAP's build infra can pull it) and ships maap-py plus the DPS
# credential plumbing that maap.aws.earthdata_s3_credentials() relies on.
#
# build.sh creates two conda envs at registration time:
#   rift_nisar2cog : slim geocoding env (rift + deps, no isce3)
#   crevasse       : nisar-crevasse gate + U-Net inference env (torch)
# and bakes the large NISAR U-Net checkpoint from my-public-bucket into the clone.
FROM mas.maap-project.org/root/maap-workspaces/custom_images/maap_base:v5.0.0

COPY . /opt/app

RUN chmod +x /opt/app/rift/maap/nisar_e2e/run.sh /opt/app/rift/maap/nisar_e2e/build.sh

ENTRYPOINT ["/opt/app/rift/maap/nisar_e2e/run.sh"]
