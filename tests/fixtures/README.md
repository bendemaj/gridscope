# Fixture provenance

These small XML documents contain **synthetic test values**, not observed Austrian
production data. Their structures follow the official ENTSO-E Postman collection's
examples for A44, A65, A75 and A11, checked on 12 September 2026:
https://documenter.getpostman.com/view/7009892/2s93JtP3F6

The fixtures deliberately share a one-hour interval to test cross-dataset alignment.
Generation includes a pumping-consumption series to verify that it is excluded.
Tests mutate these structures to exercise missing publications, A03 blocks, duplicate
positions, malformed data, pagination and direction errors. No production token or
account information is embedded. Examples use live data by default; tests inject
these fixtures through HTTPX MockTransport.
