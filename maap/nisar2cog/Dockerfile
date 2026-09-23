# Built on MAAP's maap_base image, which lives in the private mas.maap-project.org
# registry (only MAAP's build infra can pull it) and ships maap-py plus the DPS
# credential plumbing that maap.aws.earthdata_s3_credentials() relies on.
#
# The conda env (rift + deps, no isce3) is created by build.sh at registration time.
FROM mas.maap-project.org/root/maap-workspaces/custom_images/maap_base:v5.0.0

COPY . /opt/app

RUN chmod +x /opt/app/rift/maap/nisar2cog/run.sh /opt/app/rift/maap/nisar2cog/build.sh

ENTRYPOINT ["/opt/app/rift/maap/nisar2cog/run.sh"]
