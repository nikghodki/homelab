# ghcr.io/nikghodki/open-webui: "Ask Me", the household's Open WebUI (runbooks/open-webui.md, "Ask Me overlay").
# The upstream image plus one small patch (patch_branding.py): no " (Open WebUI)" after WEBUI_NAME, and the page
# title before the app loads. Nothing else changes; the copyright notices and licence comments in the source stay.
# Licence: the Open WebUI License (BSD-3 plus a branding clause, LICENSE.open-webui) allows changing the branding only
# for deployments with at most 50 end users in any rolling 30 days; this household deployment qualifies. Anyone who
# runs or redistributes this rebranded image is bound by the same clause.
# Tag: <upstream tag>-askme.<askme-revision> (.github/scripts/image-spec.sh); bump the revision when the patch
# changes on the same upstream version. Renovate bumps the FROM line; CI builds the overlay on every such PR, so a
# patch that no longer applies fails the PR.
# askme-revision: 1
FROM ghcr.io/open-webui/open-webui:v0.13.3@sha256:46b59158e6558eeb980bc828e0f1b30238ad24d82ed84d5e5eda1dab2a082f14
ARG ASKME_TITLE="Ask Me"
COPY LICENSE.open-webui /app/LICENSE.open-webui
COPY patch_branding.py /tmp/patch_branding.py
RUN python3 /tmp/patch_branding.py --root /app --title "$ASKME_TITLE" && rm /tmp/patch_branding.py
