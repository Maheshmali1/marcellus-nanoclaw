import fs from 'fs';
import os from 'os';
import { logger } from './logger.js';
/** The container runtime binary name. */
export const CONTAINER_RUNTIME_BIN = 'docker';
/** Hostname containers use to reach the host machine. */
export const CONTAINER_HOST_GATEWAY = 'host.docker.internal';
/**
 * Address the credential proxy binds to.
 * Docker Desktop (macOS): 127.0.0.1 — the VM routes host.docker.internal to loopback.
 * Docker (Linux): bind to the docker0 bridge IP so only containers can reach it,
 *   falling back to 0.0.0.0 if the interface isn't found.
 */
export const PROXY_BIND_HOST = process.env.CREDENTIAL_PROXY_HOST || detectProxyBindHost();
function detectProxyBindHost() {
    if (os.platform() === 'darwin')
        return '127.0.0.1';
    // WSL uses Docker Desktop (same VM routing as macOS) — loopback is correct.
    // Check /proc filesystem, not env vars — WSL_DISTRO_NAME isn't set under systemd.
    if (fs.existsSync('/proc/sys/fs/binfmt_misc/WSLInterop'))
        return '127.0.0.1';
    // Bare-metal Linux: bind to the docker0 bridge IP instead of 0.0.0.0
    const ifaces = os.networkInterfaces();
    const docker0 = ifaces['docker0'];
    if (docker0) {
        const ipv4 = docker0.find((a) => a.family === 'IPv4');
        if (ipv4)
            return ipv4.address;
    }
    return '0.0.0.0';
}
/** CLI args needed for the container to resolve the host gateway. */
export function hostGatewayArgs() {
    // On Linux, host.docker.internal isn't built-in — add it explicitly
    if (os.platform() === 'linux') {
        return ['--add-host=host.docker.internal:host-gateway'];
    }
    return [];
}
/** Returns CLI args for a readonly bind mount. */
export function readonlyMountArgs(hostPath, containerPath) {
    return ['-v', `${hostPath}:${containerPath}:ro`];
}
/** Returns the shell command to stop a container by name. */
export function stopContainer(name) {
    return `${CONTAINER_RUNTIME_BIN} stop -t 1 ${name}`;
}
/** No-op in no-docker mode — agents run directly via Node.js. */
export function ensureContainerRuntimeRunning() {
    logger.debug('No-docker mode: skipping container runtime check');
}
/** No-op in no-docker mode. */
export function cleanupOrphans() {
    logger.debug('No-docker mode: skipping orphan cleanup');
}
//# sourceMappingURL=container-runtime.js.map