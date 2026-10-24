# Docker setup

The image includes Python and FFmpeg. There is no need to install them on the Mac. These instructions use Docker Compose v2 and Docker Desktop's Linux containers.

The container runs as UID **501**, GID **20** by default, matching the ownership used in your existing Mac services. Settings, artwork cache, index and queued uploads live in the persistent `/data` volume. Music lives in the host directory you bind to `/music`.

## Add MediaDrop to your existing stack

In Terminal, change to the directory containing your existing Docker Compose file. Clone this repository into its own subdirectory:

```sh
git clone https://github.com/colintdf/mediadrop.git mediadrop
```

Add this variable to your stack's existing `.env` file, substituting your actual music library path:

```dotenv
MEDIADROP_MUSIC_PATH="/full/path/to/your/music/library"
```

Use an existing directory. The bind mount deliberately refuses to create a missing directory. If your external drive is not mounted, mount it in Finder before starting the service. In Docker Desktop, allow file sharing for that directory if requested.

Add this service **inside your existing `services:` block**, at the same indentation level as `slskd`, `caddy`, etc. Do not add a second `services:` block:

```yaml
  mediadrop:
    build:
      context: ./mediadrop
      args:
        PUID: "501"
        PGID: "20"
    image: mediadrop:local
    container_name: mediadrop
    restart: unless-stopped
    init: true
    stop_grace_period: 60s
    ports:
      - "12345:12345"
    environment:
      TZ: Europe/London
    volumes:
      - mediadrop_data:/data
      - type: bind
        source: ${MEDIADROP_MUSIC_PATH:?Set MEDIADROP_MUSIC_PATH in .env}
        target: /music
        bind:
          create_host_path: false
    read_only: true
    tmpfs:
      - /tmp:size=256m,mode=1777
```

Add the following at the top level, alongside your existing `networks:` block:

```yaml
volumes:
  mediadrop_data:
```

If your stack already has a top-level `volumes:` block, add `mediadrop_data:` to that block. MediaDrop uses the stack's default network; it can be reached directly on your LAN and does not depend on Gluetun or the VPN.

Stop the standalone MediaDrop server with Control+C to free port 12345, then run from your existing stack directory:

```sh
docker compose config --quiet
docker compose up -d --build mediadrop
docker compose logs mediadrop
```

Open **http://localhost:12345** on the Mac, or **http://YOUR-MAC-IP:12345** on another device. No password is required. In **Manage folders**, add **`/music`** as your music destination. The container sees `/music`; you should not enter the host's `/Users/...` or `/Volumes/...` path in that field unless you separately mounted it at that same path.

The service now participates in your normal `docker compose up -d` commands. `restart: unless-stopped` brings an existing container back when the Docker engine restarts, unless you explicitly stopped it. Enable Docker Desktop's **Start Docker Desktop when you sign in to your computer** option if you want it started at Mac login. This is login-based; a Mac waiting at its login screen after reboot may not have Docker Desktop running yet. A healthy Docker engine and mounted music drive are still required.

Your stack's existing autoheal service is configured to monitor all health-checked containers. The Docker image includes a health check; it will therefore be included by that existing setting without adding another autoheal container.

## Alternative: supplementary Compose file

If you prefer keeping the new service separate, leave the original Compose YAML alone and use the included `compose.stack.yaml`:

```sh
docker compose -f compose.yaml -f mediadrop/compose.stack.yaml up -d --build mediadrop
```

Replace the first filename with your current Compose filename if different. Continue using **both** `-f` arguments for future full-stack commands, or set `COMPOSE_FILE=compose.yaml:mediadrop/compose.stack.yaml` in the stack's `.env`. Relative paths in the supplementary file are resolved from the directory of the first Compose file, which is why its build context is `./mediadrop`.

## Run as its own Compose project

```sh
git clone https://github.com/colintdf/mediadrop.git
cd mediadrop
cp .env.example .env
```

Edit `.env` to set `MEDIADROP_MUSIC_PATH`, then run:

```sh
docker compose up -d --build
docker compose logs mediadrop
```

This also restarts automatically with Docker, but appears as a separate Compose project in Docker Desktop. Use either the existing-stack route or the separate-project route for a given instance, as both use container name `mediadrop` and port 12345.

## Connect Plex and Lidarr artwork

In MediaDrop's **Artwork** settings:

- If Plex runs directly on this Mac, use `http://host.docker.internal:32400` with your Plex token.
- If Lidarr runs directly on this Mac, use `http://host.docker.internal:8686` with its API key.
- For a service in the same Compose network, use its service name, such as `http://lidarr:8686`.
- For another device, use its LAN IP and port.

`localhost` in a container refers to that container. It does not reach the Mac host or another container. Docker Desktop needs macOS Local Network permission to reach other LAN devices. Credentials are entered in the web UI and remain in `/data/config.json`; do not commit them to GitHub.

No reverse proxy or public internet exposure is required. The current application serves HTTP and is intended for your trusted home network. Do not add it to a public Caddy/Cloudflare route as part of this setup.

## Updating and stopping

From your existing stack directory after integrating the service:

```sh
git -C mediadrop pull --ff-only
docker compose up -d --build mediadrop
```

To stop only MediaDrop:

```sh
docker compose stop mediadrop
```

To bring it back:

```sh
docker compose up -d mediadrop
```

Rebuilding/recreating the container keeps the named data volume and host music files. Do not run `docker compose down --volumes` against your real stack: it removes named volumes, including MediaDrop settings and any other volumes in that stack. Back up the music directory and state volume as appropriate.

## Existing native installation

Docker starts with its own settings volume and opens directly without a password. Your existing audio files and their saved metadata remain in the mounted music directory. Add `/music` and scan to populate the Docker library. Keep the old native settings folder as a backup.

This setup does not automatically import the native transfer queue or destination paths: those destination paths refer to the Mac filesystem and need container mount paths. Finish outstanding native uploads/conversions before switching. You can continue using the original Mac launchers if you choose to return to native mode; stop the container first so port 12345 is free.

## Permissions and troubleshooting

The PUID/PGID values are **build arguments** for this image, unlike LinuxServer images that change identity at runtime. Set them before building. In a typical Linux install use your actual numeric UID/GID, commonly 1000/1000. Changing them later requires adjusting ownership of an existing settings volume to the new identity; rebuilding alone does not change that volume's ownership.

- **Address already in use:** stop the old native MediaDrop server or another container bound to port 12345.
- **Bind source path does not exist:** mount the drive and check `MEDIADROP_MUSIC_PATH` in `.env`.
- **Folder unavailable in the UI:** use `/music`, and check the Docker bind mount.
- **Permission denied:** check the host directory's permissions and Docker Desktop file-sharing settings. Do not recursively change ownership of your music library just to diagnose this.
- **Settings disappeared:** verify you are using the same Compose project and data volume; changing project names creates differently named volumes.
- **Artwork cannot connect:** use the host, service-name or LAN addresses above, and check the configured token/API key.

Official Docker references: [Compose service and volume settings](https://docs.docker.com/reference/compose-file/services/), [Docker Desktop networking](https://docs.docker.com/desktop/features/networking/networking-how-tos/), and [Docker Desktop startup settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/).
