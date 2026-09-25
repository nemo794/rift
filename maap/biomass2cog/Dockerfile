# Built on MAAP's maap_base image, which lives in the private mas.maap-project.org
# registry (only MAAP's build infra can pull it) and ships maap-py plus the DPS
# credential plumbing that MAAP().secrets relies on.
#
# The conda env (isce3 + biomass-reader + rift + ESA-access deps) is created by
# build.sh at registration time.
FROM mas.maap-project.org/root/maap-workspaces/custom_images/maap_base:v5.0.0

COPY . /opt/app

RUN chmod +x /opt/app/rift/maap/biomass2cog/run.sh /opt/app/rift/maap/biomass2cog/build.sh

ENTRYPOINT ["/opt/app/rift/maap/biomass2cog/run.sh"]
