# Egress proxy for the shared_budget sandbox agent.
#
# This is the ONLY container in the sandbox with a route to the internet.
# The agent container sits on an internal Docker network (no gateway out)
# and can reach the internet only by tunneling through this proxy, which
# allows CONNECT only to domains listed in squid.conf.

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends squid \
    && rm -rf /var/lib/apt/lists/*

COPY squid.conf /etc/squid/squid.conf
RUN sed -i 's/\r$//' /etc/squid/squid.conf

EXPOSE 3128

# -N: stay in the foreground (needed for `docker compose logs`).
CMD ["squid", "-N", "-d", "1"]
