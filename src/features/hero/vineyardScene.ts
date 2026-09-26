import * as THREE from "thrhttp://localhost:5173/loginee";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

/** Scene units are metres. Rows run along z, towards the camera; the drone sweeps bands across them. */
export const FIELD = {
  x0: -56,
  x1: 56,
  zFar: -96,
  zNear: 20,
  rowSpacing: 2.8,
  vineSpacing: 1.25,
  bands: 8,
  headland: 6,
} as const;
export const ROW_COUNT = Math.round((FIELD.x1 - FIELD.x0) / FIELD.rowSpacing);
const BAND_WIDTH = (FIELD.zNear - FIELD.zFar) / FIELD.bands;
const BACK = { z0: -122, rows: 16, spacing: 2.6, halfWidth: 92 };

const ALTITUDE = 11;
const SPEED = 17;
const FOOTPRINT = 7.5;
const HOLD_S = 1.4;
const ROUTE_DRAW_S = 6;
const ROUTE_HOLD_S = 4.5;
const RETURN_S = 6.5;
const ORIGIN = { lat: 47.1230335, lon: 28.7073776 };

// Site palette: canopy green, row lime, inter-row gold, waste orange, route violet.
const COLORS = {
  soil: "#8a6a45",
  grass: "#4a7d34",
  grassDark: "#16301a",
  canopyDark: "#1f5a2c",
  canopyLight: "#86cf57",
  canopyLine: "#4fd67a",
  row: "#c6e98a",
  interrow: "#f5c451",
  waste: "#ffb547",
  route: "#a08cff",
  halo: "#f4ffe6",
  sun: "#f7e3a4",
  ambient: "#3a5e6e",
  fog: "#23443c",
  skyTop: "#0a1a2a",
  skyHorizon: "#3a6a58",
  tree: "#0e2618",
  post: "#6b4a2b",
  body: "#1b2523",
};

export type SurveyPhase = "scanning" | "turning" | "complete" | "routing" | "returning";

export interface Marker {
  x: number;
  z: number;
  found: boolean;
}

export interface Telemetry {
  phase: SurveyPhase;
  band: number;
  bands: number;
  coverage: number;
  rowsDetected: number;
  vinesAnalysed: number;
  vinesTotal: number;
  waste: Marker[];
  gaps: Marker[];
  routeProgress: number;
  routeLengthM: number;
  altitude: number;
  speedKmh: number;
  lat: number;
  lon: number;
  drone: { x: number; z: number; heading: number };
  scan: { band: number; progress: number; intensity: number };
}

export interface SceneLayout {
  rowXs: number[];
  vines: Array<[x: number, z: number]>;
  route: Array<[x: number, z: number]>;
  waste: Marker[];
  gaps: Array<Marker & { z1: number }>;
}

export interface SceneOptions {
  /** Draw one still frame and skip the render loop. */
  still: boolean;
  onTelemetry: (telemetry: Telemetry) => void;
  /** Drone position in CSS pixels, every frame. */
  onDroneScreen: (x: number, y: number, visible: boolean) => void;
  onReady: () => void;
}

export interface VineyardScene {
  layout: SceneLayout;
  resize(): void;
  setPointer(x: number, y: number): void;
  setRunning(running: boolean): void;
  dispose(): void;
}

function rng(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const smooth = (edge0: number, edge1: number, value: number) => {
  const t = Math.min(1, Math.max(0, (value - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
};

export function terrainHeight(x: number, z: number): number {
  const rolling = 1.2 * Math.sin(x * 0.045 + 0.6) * Math.cos(z * 0.03) + 0.7 * Math.sin(z * 0.07 + x * 0.02);
  const slope = 20 * smooth(-108, -178, z);
  const ridge = 12 * smooth(-178, -250, z) + 3 * Math.sin(x * 0.02) * smooth(-170, -230, z);
  const valleySides = 0.0005 * Math.max(0, Math.abs(x) - 80) ** 2;
  return rolling + slope + ridge + valleySides;
}

const rowX = (i: number) => FIELD.x0 + (i + 0.5) * FIELD.rowSpacing;

/** Mirror of `scanned()` in GLSL, for the HUD counts and layer panels. */
export function scannedAt(x: number, z: number, band: number, progress: number): boolean {
  if (x < FIELD.x0 || x > FIELD.x1 || z < FIELD.zFar || z > FIELD.zNear) return false;
  const b = Math.floor((z - FIELD.zFar) / BAND_WIDTH);
  if (b < band) return true;
  if (b > band) return false;
  const u = (x - FIELD.x0) / (FIELD.x1 - FIELD.x0);
  return (b % 2 === 0 ? u : 1 - u) <= progress;
}

const f1 = (value: number) => value.toFixed(2);

const SCAN_GLSL = /* glsl */ `
uniform vec4 uScan;
uniform vec3 uDrone;
uniform float uFootprint;
uniform float uTime;
uniform vec3 uFogColor;
uniform float uFogDensity;

const float FX0 = ${f1(FIELD.x0)};
const float FX1 = ${f1(FIELD.x1)};
const float FZF = ${f1(FIELD.zFar)};
const float FZN = ${f1(FIELD.zNear)};
const float BW = ${f1(BAND_WIDTH)};

float fieldMask(vec2 p) {
  return step(FX0, p.x) * step(p.x, FX1) * step(FZF, p.y) * step(p.y, FZN);
}

float footprint(vec2 p) {
  return 1.0 - smoothstep(uFootprint * 0.82, uFootprint, distance(p, uDrone.xz));
}

float scanned(vec2 p) {
  float band = floor((p.y - FZF) / BW);
  float u = (p.x - FX0) / (FX1 - FX0);
  float along = mod(band, 2.0) < 0.5 ? u : 1.0 - u;
  float s = band < uScan.x - 0.5 ? 1.0 : (abs(band - uScan.x) < 0.5 ? step(along, uScan.y) : 0.0);
  s = max(s * uScan.z, footprint(p));
  return s * fieldMask(p);
}

vec3 applyFog(vec3 color, vec3 world) {
  float d = distance(world, cameraPosition);
  float f = 1.0 - exp(-uFogDensity * uFogDensity * d * d);
  return mix(color, uFogColor, f);
}
`;

const PASS_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const color = (hex: string, scale = 1) => new THREE.Color(hex).multiplyScalar(scale);

function sharedUniforms(sunDir: THREE.Vector3) {
  return {
    uScan: { value: new THREE.Vector4(0, 0, 1, 0) },
    uDrone: { value: new THREE.Vector3() },
    uFootprint: { value: FOOTPRINT },
    uTime: { value: 0 },
    uFogColor: { value: color(COLORS.fog) },
    uFogDensity: { value: 0.0058 },
    uSunDir: { value: sunDir },
    uSunColor: { value: color(COLORS.sun, 1.6) },
    uAmbient: { value: color(COLORS.ambient, 0.85) },
    uLime: { value: color(COLORS.row) },
    uCanopy: { value: color(COLORS.canopyLine) },
    uGold: { value: color(COLORS.interrow) },
    uViolet: { value: color(COLORS.route) },
  };
}

type Shared = ReturnType<typeof sharedUniforms>;

function buildTerrain(shared: Shared, gaps: SceneLayout["gaps"]) {
  const geometry = new THREE.PlaneGeometry(760, 620, 300, 250);
  geometry.rotateX(-Math.PI / 2);
  geometry.translate(0, 0, -150);
  const position = geometry.attributes.position;
  for (let i = 0; i < position.count; i++) {
    position.setY(i, terrainHeight(position.getX(i), position.getZ(i)));
  }
  geometry.computeVertexNormals();
  const h = FIELD.headland;

  const material = new THREE.ShaderMaterial({
    uniforms: {
      ...shared,
      uSoil: { value: color(COLORS.soil) },
      uGrass: { value: color(COLORS.grass) },
      uGrassDark: { value: color(COLORS.grassDark) },
      uGaps: { value: gaps.map((g) => new THREE.Vector4(g.x, g.z, g.z1, 0)) },
    },
    vertexShader: /* glsl */ `
      varying vec3 vWorld;
      varying vec3 vNormal;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        vNormal = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      ${SCAN_GLSL}
      uniform vec3 uSunDir, uSunColor, uAmbient, uLime, uGold, uViolet, uSoil, uGrass, uGrassDark;
      uniform vec4 uGaps[${gaps.length}];
      varying vec3 vWorld;
      varying vec3 vNormal;

      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float noise(vec2 p) {
        vec2 i = floor(p), f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
      }

      void main() {
        vec2 p = vWorld.xz;
        vec3 n = normalize(vNormal);
        float grain = noise(p * 0.12) * 0.6 + noise(p * 0.7) * 0.4;
        float pebbles = noise(p * 3.1);
        vec3 grass = mix(uGrassDark, uGrass, grain * 0.85);

        // Soil plot with headlands, a ragged grass fringe, and greener strips under the rows.
        float edge = min(min(p.x - (FX0 - ${f1(h)}), (FX1 + ${f1(h)}) - p.x), min(p.y - (FZF - ${f1(h)}), (FZN + ${f1(h)}) - p.y));
        float plot = smoothstep(-0.4, 0.9, edge + (noise(p * 0.9) - 0.5) * 1.6);
        float fringe = (1.0 - smoothstep(0.0, 1.6, abs(edge + 0.3))) * 0.9;
        vec3 soil = uSoil * (0.7 + grain * 0.35 + pebbles * 0.18);
        float rowPhase = abs(fract((p.x - FX0) / ${f1(FIELD.rowSpacing)}) - 0.5) * 2.0;
        float underRow = (1.0 - smoothstep(0.15, 0.45, rowPhase)) * fieldMask(p);
        vec3 base = mix(grass, mix(soil, uGrassDark * 1.3, underRow * 0.7), plot);
        base = mix(base, uGrass * 1.25, fringe * (0.6 + grain * 0.4));

        float inBack = step(${f1(BACK.z0 - BACK.rows * BACK.spacing)}, p.y) * step(p.y, ${f1(BACK.z0 + 1)})
          * step(abs(p.x), ${f1(BACK.halfWidth)});
        float backPhase = abs(fract((p.y - ${f1(BACK.z0)}) / ${f1(BACK.spacing)}) - 0.5) * 2.0;
        base = mix(base, mix(uGrassDark * 1.2, soil * 0.8, smoothstep(0.3, 0.75, backPhase)), inBack);

        float diffuse = max(dot(n, uSunDir), 0.0);
        vec3 color = base * (uAmbient + uSunColor * diffuse);

        float s = scanned(p);
        float interrow = smoothstep(0.45, 0.8, rowPhase) * fieldMask(p);
        color = mix(color, color * 0.7 + uGold * 0.14, s * interrow);

        vec2 cell = p / 4.0;
        vec2 grid = abs(fract(cell - 0.5) - 0.5) / fwidth(cell);
        color += uLime * (1.0 - min(min(grid.x, grid.y), 1.0)) * 0.34 * s;

        vec2 toDrone = p - uDrone.xz;
        float d = length(toDrone);
        float ring = 1.0 - smoothstep(0.0, 0.35 + fwidth(d) * 1.5, abs(d - uFootprint));
        float inner = 1.0 - smoothstep(0.0, 0.2 + fwidth(d), abs(d - uFootprint * 0.55));
        float sweep = pow(fract(atan(toDrone.y, toDrone.x) / 6.28318 - uTime * 0.45), 10.0) * step(d, uFootprint);
        color += uLime * (ring * 2.4 + inner * 0.6 + sweep * 0.9 + footprint(p) * 0.12) * step(0.01, uFootprint);

        for (int i = 0; i < ${gaps.length}; i++) {
          vec4 g = uGaps[i];
          float inGap = step(abs(p.x - g.x), 0.8) * step(g.y, p.y) * step(p.y, g.z);
          color += uViolet * inGap * g.w * (0.7 + 0.3 * sin(uTime * 4.0));
        }

        gl_FragColor = vec4(applyFog(color, vWorld), 1.0);
      }
    `,
  });
  return new THREE.Mesh(geometry, material);
}

interface Placement {
  matrices: THREE.Matrix4[];
  seeds: number[];
  centres: Array<[number, number, number, number]>;
}

function placeVines(random: () => number, gaps: SceneLayout["gaps"]) {
  const placement: Placement = { matrices: [], seeds: [], centres: [] };
  const posts: Array<[number, number]> = [];
  const frontVines: Array<[number, number]> = [];
  const dummy = new THREE.Object3D();
  const add = (x: number, z: number, front: boolean) => {
    const sx = 1.05 + random() * 0.3;
    const sy = 1.15 + random() * 0.4;
    const px = x + (random() - 0.5) * 0.12;
    const y = terrainHeight(px, z) + 0.62 * sy * 0.78;
    dummy.position.set(px, y, z);
    dummy.rotation.set(0, random() * Math.PI, 0);
    dummy.scale.set(sx, sy, 0.95 + random() * 0.3);
    dummy.updateMatrix();
    placement.matrices.push(dummy.matrix.clone());
    placement.seeds.push(random());
    if (front) {
      placement.centres.push([px, y, z, sx * 0.72]);
      frontVines.push([px, z]);
    }
  };

  for (let i = 0; i < ROW_COUNT; i++) {
    const x = rowX(i);
    let count = 0;
    for (let z = FIELD.zNear - 1; z > FIELD.zFar + 1; z -= FIELD.vineSpacing) {
      if (count++ % 5 === 0) posts.push([x, z + FIELD.vineSpacing / 2]);
      if (gaps.some((gap) => Math.abs(gap.x - x) < 0.1 && z >= gap.z && z <= gap.z1)) continue;
      add(x, z, true);
    }
    posts.push([x, FIELD.zFar + 0.6]);
  }
  const front = placement.matrices.length;
  for (let j = 0; j < BACK.rows; j++) {
    const z = BACK.z0 - (j + 0.5) * BACK.spacing;
    for (let x = -BACK.halfWidth + 1; x < BACK.halfWidth - 1; x += 1.2) add(x, z, false);
  }
  return { front, placement, posts, frontVines };
}

function buildVines(shared: Shared, { matrices, seeds }: Placement) {
  const geometry = new THREE.IcosahedronGeometry(0.62, 1);
  geometry.setAttribute("aSeed", new THREE.InstancedBufferAttribute(new Float32Array(seeds), 1));
  const material = new THREE.ShaderMaterial({
    uniforms: {
      ...shared,
      uDark: { value: color(COLORS.canopyDark) },
      uLight: { value: color(COLORS.canopyLight) },
    },
    vertexShader: /* glsl */ `
      attribute float aSeed;
      uniform float uTime;
      varying vec3 vWorld;
      varying float vSeed;
      varying float vTop;
      void main() {
        vec3 p = position;
        p += normal * (sin(p.x * 9.0 + aSeed * 20.0) * sin(p.z * 7.0) * 0.08);
        vec4 world = modelMatrix * instanceMatrix * vec4(p, 1.0);
        world.x += sin(uTime * 1.4 + world.z * 0.35 + aSeed * 6.0) * 0.05 * max(position.y, 0.0);
        vWorld = world.xyz;
        vSeed = aSeed;
        vTop = position.y / 0.62;
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      ${SCAN_GLSL}
      uniform vec3 uSunDir, uSunColor, uAmbient, uCanopy, uDark, uLight;
      varying vec3 vWorld;
      varying float vSeed;
      varying float vTop;
      void main() {
        vec3 n = normalize(cross(dFdx(vWorld), dFdy(vWorld)));
        vec3 viewDir = normalize(cameraPosition - vWorld);
        if (dot(n, viewDir) < 0.0) n = -n;
        vec3 base = mix(uDark, uLight, clamp(vSeed * 0.4 + vTop * 0.4 + 0.25, 0.0, 1.0));
        float diffuse = max(dot(n, uSunDir), 0.0);
        float rim = pow(1.0 - max(dot(n, viewDir), 0.0), 3.0) * max(dot(-viewDir, uSunDir) * 0.5 + 0.5, 0.0);
        vec3 color = base * (uAmbient + uSunColor * diffuse) + uSunColor * rim * 0.3;
        float s = scanned(vWorld.xz);
        color = mix(color, color * 0.75 + uCanopy * (0.18 + 0.3 * diffuse), s * 0.45) + uCanopy * rim * s * 0.5;
        color += uCanopy * footprint(vWorld.xz) * (0.5 + 0.5 * sin(uTime * 8.0 + vWorld.z)) * 0.3;
        gl_FragColor = vec4(applyFog(color, vWorld), 1.0);
      }
    `,
  });
  const mesh = new THREE.InstancedMesh(geometry, material, matrices.length);
  matrices.forEach((matrix, index) => mesh.setMatrixAt(index, matrix));
  mesh.instanceMatrix.needsUpdate = true;
  mesh.frustumCulled = false;
  return mesh;
}

/** One outline per vine plant, like the canopy polygons: appears where the scan has passed. */
function buildCanopyOutlines(shared: Shared, centres: Placement["centres"]) {
  const geometry = new THREE.RingGeometry(0.93, 1, 28);
  geometry.rotateX(-Math.PI / 2);
  const material = new THREE.ShaderMaterial({
    uniforms: { ...shared },
    side: THREE.DoubleSide,
    depthWrite: false,
    transparent: true,
    vertexShader: /* glsl */ `
      varying vec3 vWorld;
      varying vec3 vCentre;
      void main() {
        vec4 world = modelMatrix * instanceMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        vCentre = (modelMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      ${SCAN_GLSL}
      uniform vec3 uCanopy;
      varying vec3 vWorld;
      varying vec3 vCentre;
      void main() {
        float s = scanned(vCentre.xz);
        if (s < 0.02) discard;
        float flash = footprint(vCentre.xz);
        gl_FragColor = vec4(applyFog(uCanopy * (1.7 + flash * 2.5), vWorld), s);
      }
    `,
  });
  const mesh = new THREE.InstancedMesh(geometry, material, centres.length);
  const dummy = new THREE.Object3D();
  centres.forEach(([x, y, z, radius], index) => {
    dummy.position.set(x, y + 0.05, z);
    dummy.scale.set(radius, 1, radius * 0.95);
    dummy.updateMatrix();
    mesh.setMatrixAt(index, dummy.matrix);
  });
  mesh.instanceMatrix.needsUpdate = true;
  mesh.frustumCulled = false;
  return mesh;
}

function buildPosts(posts: Array<[number, number]>) {
  const geometry = new THREE.BoxGeometry(0.12, 2.3, 0.12);
  geometry.translate(0, 1.0, 0);
  const material = new THREE.MeshStandardMaterial({ color: COLORS.post, roughness: 0.9 });
  const mesh = new THREE.InstancedMesh(geometry, material, posts.length);
  const dummy = new THREE.Object3D();
  posts.forEach(([x, z], index) => {
    dummy.position.set(x, terrainHeight(x, z) - 0.1, z);
    dummy.rotation.set((Math.sin(x * z) - 0.5) * 0.06, 0, Math.cos(x + z) * 0.05);
    dummy.updateMatrix();
    mesh.setMatrixAt(index, dummy.matrix);
  });
  mesh.instanceMatrix.needsUpdate = true;
  return mesh;
}

/** Glowing row axes above each front row, revealed where the field is scanned. */
function buildRowAxes(shared: Shared, gaps: SceneLayout["gaps"]) {
  const positions: number[] = [];
  const along: number[] = [];
  const gapFlags: number[] = [];
  const indices: number[] = [];
  const half = 0.075;
  let vertex = 0;
  for (let i = 0; i < ROW_COUNT; i++) {
    const x = rowX(i);
    const start = vertex;
    for (let z = FIELD.zNear - 0.5; z >= FIELD.zFar + 0.5; z -= 2) {
      const y = terrainHeight(x, z) + 1.95;
      const inGap = gaps.some((gap) => Math.abs(gap.x - x) < 0.1 && z >= gap.z - 1 && z <= gap.z1 + 1) ? 1 : 0;
      positions.push(x - half, y, z, x + half, y, z);
      along.push(FIELD.zNear - z, FIELD.zNear - z);
      gapFlags.push(inGap, inGap);
      vertex += 2;
    }
    for (let v = start; v < vertex - 2; v += 2) indices.push(v, v + 1, v + 2, v + 1, v + 3, v + 2);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("aAlong", new THREE.Float32BufferAttribute(along, 1));
  geometry.setAttribute("aGap", new THREE.Float32BufferAttribute(gapFlags, 1));
  geometry.setIndex(indices);

  const material = new THREE.ShaderMaterial({
    uniforms: { ...shared },
    side: THREE.DoubleSide,
    vertexShader: /* glsl */ `
      attribute float aAlong;
      attribute float aGap;
      varying vec3 vWorld;
      varying float vAlong;
      varying float vGap;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        vAlong = aAlong;
        vGap = aGap;
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      ${SCAN_GLSL}
      uniform vec3 uLime, uViolet;
      varying vec3 vWorld;
      varying float vAlong;
      varying float vGap;
      void main() {
        float s = scanned(vWorld.xz);
        if (s < 0.02) discard;
        float pulse = pow(fract(vAlong * 0.025 - uTime * 0.5), 14.0);
        vec3 color = mix(uLime, uViolet, vGap) * (0.75 + pulse * 2.6);
        gl_FragColor = vec4(applyFog(color * s, vWorld), 1.0);
      }
    `,
  });
  return new THREE.Mesh(geometry, material);
}

/** Rounds each corner of a polyline with a quadratic curve. */
function fillet(points: Array<[number, number]>, radius: number): Array<[number, number]> {
  const out: Array<[number, number]> = [points[0]];
  for (let i = 1; i < points.length - 1; i++) {
    const [ax, az] = points[i - 1];
    const [bx, bz] = points[i];
    const [cx, cz] = points[i + 1];
    const inLength = Math.hypot(bx - ax, bz - az);
    const outLength = Math.hypot(cx - bx, cz - bz);
    const r = Math.min(radius, inLength / 2, outLength / 2);
    const p0: [number, number] = [bx - ((bx - ax) / inLength) * r, bz - ((bz - az) / inLength) * r];
    const p2: [number, number] = [bx + ((cx - bx) / outLength) * r, bz + ((cz - bz) / outLength) * r];
    for (let k = 0; k <= 6; k++) {
      const t = k / 6;
      const u = 1 - t;
      out.push([u * u * p0[0] + 2 * u * t * bx + t * t * p2[0], u * u * p0[1] + 2 * u * t * bz + t * t * p2[1]]);
    }
  }
  out.push(points[points.length - 1]);
  return out;
}

/** Walking route: every second inter-row, joined on the headlands, back to the start. */
function planRoute(): Array<[number, number]> {
  const near = FIELD.zNear + 3;
  const far = FIELD.zFar - 3;
  const start: [number, number] = [FIELD.x0 - 3, near];
  const corners: Array<[number, number]> = [start];
  let atFar = false;
  for (let k = 0; k < ROW_COUNT - 1; k += 2) {
    const x = FIELD.x0 + (k + 1) * FIELD.rowSpacing;
    corners.push([x, atFar ? far : near], [x, atFar ? near : far]);
    atFar = !atFar;
  }
  if (atFar) corners.push([FIELD.x1 + 3, far], [FIELD.x1 + 3, near]);
  corners.push([FIELD.x1 + 3, near + 2.5], [FIELD.x0 - 3, near + 2.5], start);
  return fillet(corners, 1.3);
}

function buildRoute(shared: Shared, route: Array<[number, number]>) {
  const positions: number[] = [];
  const dist: number[] = [];
  const side: number[] = [];
  const indices: number[] = [];
  const half = 0.36;
  let total = 0;
  route.forEach(([x, z], i) => {
    const [px, pz] = route[Math.max(0, i - 1)];
    const [nx, nz] = route[Math.min(route.length - 1, i + 1)];
    if (i > 0) total += Math.hypot(x - px, z - pz);
    const dx = nx - px;
    const dz = nz - pz;
    const length = Math.hypot(dx, dz) || 1;
    const ox = (-dz / length) * half;
    const oz = (dx / length) * half;
    positions.push(x + ox, terrainHeight(x + ox, z + oz) + 0.07, z + oz, x - ox, terrainHeight(x - ox, z - oz) + 0.07, z - oz);
    dist.push(total, total);
    side.push(1, -1);
    if (i > 0) {
      const v = i * 2;
      indices.push(v - 2, v - 1, v, v - 1, v + 1, v);
    }
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("aDist", new THREE.Float32BufferAttribute(dist, 1));
  geometry.setAttribute("aSide", new THREE.Float32BufferAttribute(side, 1));
  geometry.setIndex(indices);

  const uRoute = { value: new THREE.Vector2(0, 0) };
  const material = new THREE.ShaderMaterial({
    uniforms: { ...shared, uRoute, uLength: { value: total }, uHalo: { value: color(COLORS.halo) } },
    side: THREE.DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: -4,
    vertexShader: /* glsl */ `
      attribute float aDist;
      attribute float aSide;
      varying vec3 vWorld;
      varying float vDist;
      varying float vSide;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        vDist = aDist;
        vSide = aSide;
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      ${SCAN_GLSL}
      uniform vec2 uRoute;
      uniform float uLength;
      uniform vec3 uViolet, uHalo;
      varying vec3 vWorld;
      varying float vDist;
      varying float vSide;
      void main() {
        float head = uRoute.x * uLength;
        if (vDist > head || uRoute.y < 0.01) discard;
        float t = fract((vDist - uTime * 5.0) / 4.0);
        float chevron = 1.0 - smoothstep(0.0, 0.08, abs(t - 0.55 + abs(vSide) * 0.18));
        float border = smoothstep(0.55, 1.0, abs(vSide));
        float tip = 1.0 - smoothstep(0.0, 3.0, head - vDist);
        vec3 color = uViolet * (1.0 + border * 1.2) + uHalo * (chevron * 0.9 + tip * 2.5);
        gl_FragColor = vec4(applyFog(color * uRoute.y, vWorld), 1.0);
      }
    `,
  });
  return { mesh: new THREE.Mesh(geometry, material), uRoute, length: total };
}

function buildStartMarker(start: [number, number]) {
  const group = new THREE.Group();
  const [x, z] = start;
  group.position.set(x, terrainHeight(x, z) + 0.12, z);
  const flat = (geometry: THREE.BufferGeometry, hex: string, scale: number) => {
    geometry.rotateX(-Math.PI / 2);
    const material = new THREE.MeshBasicMaterial({ color: color(hex, scale), transparent: true, depthWrite: false });
    const mesh = new THREE.Mesh(geometry, material);
    group.add(mesh);
    return mesh;
  };
  flat(new THREE.CircleGeometry(1.25, 32), COLORS.halo, 2.2);
  flat(new THREE.CircleGeometry(0.95, 32), COLORS.route, 1.6);
  const ping = flat(new THREE.RingGeometry(1.3, 1.5, 40), COLORS.route, 2);
  return { group, ping };
}

function buildWaste(random: () => number, markers: Marker[]) {
  const edge = new THREE.MeshBasicMaterial({ color: color(COLORS.waste, 2.4) });
  const bar = new THREE.BoxGeometry(1, 1, 1);
  const bottleMaterial = new THREE.MeshStandardMaterial({ color: "#dfe8e4", roughness: 0.3, metalness: 0.1 });
  const capMaterial = new THREE.MeshStandardMaterial({ color: "#3b82c4", roughness: 0.4 });
  return markers.map((marker) => {
    const group = new THREE.Group();
    group.position.set(marker.x, terrainHeight(marker.x, marker.z), marker.z);
    const litter = new THREE.Group();
    for (let i = 0; i < 2 + Math.floor(random() * 2); i++) {
      const bottle = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.55, 12), bottleMaterial);
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.1, 8), capMaterial);
      cap.position.y = 0.32;
      bottle.add(cap);
      bottle.position.set((random() - 0.5) * 0.7, 0.14, (random() - 0.5) * 0.7);
      bottle.rotation.set(Math.PI / 2, random() * Math.PI, 0);
      litter.add(bottle);
    }
    group.add(litter);

    const box = new THREE.Group();
    const size = 2.2;
    const t = 0.07;
    const s = size / 2;
    const edges: Array<[number, number, number, number, number, number]> = [];
    for (const a of [-s, s]) {
      for (const b of [-s, s]) {
        edges.push([a, s, b, t, size, t], [a, b + s, 0, t, t, size], [0, a + s, b, size, t, t]);
      }
    }
    for (const [x, y, z, w, h, d] of edges) {
      const piece = new THREE.Mesh(bar, edge);
      piece.position.set(x, y, z);
      piece.scale.set(w, h, d);
      box.add(piece);
    }
    box.scale.setScalar(0.001);
    group.add(box);
    return { group, box, marker };
  });
}

function buildBeams(markers: Marker[], hex: string) {
  const geometry = new THREE.CylinderGeometry(0.3, 0.8, 12, 20, 1, true);
  geometry.translate(0, 6, 0);
  return markers.map((marker) => {
    const material = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: color(hex) }, uOpacity: { value: 0 }, uTime: { value: 0 } },
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      vertexShader: PASS_VERTEX,
      fragmentShader: /* glsl */ `
        uniform vec3 uColor;
        uniform float uOpacity;
        uniform float uTime;
        varying vec2 vUv;
        void main() {
          float flow = 0.6 + 0.4 * sin(vUv.y * 18.0 - uTime * 4.0);
          float alpha = pow(1.0 - vUv.y, 1.8) * flow * uOpacity * 0.4;
          gl_FragColor = vec4(uColor * alpha * 1.6, 1.0);
        }
      `,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(marker.x, terrainHeight(marker.x, marker.z), marker.z);
    return { mesh, material, marker };
  });
}

function buildTrees(random: () => number) {
  const geometry = new THREE.ConeGeometry(2.4, 9, 7);
  geometry.translate(0, 4.5, 0);
  const material = new THREE.MeshStandardMaterial({ color: COLORS.tree, roughness: 1, flatShading: true });
  const spots: Array<[number, number, number]> = [];
  for (let i = 0; i < 1100; i++) spots.push([(random() - 0.5) * 640, -172 - random() * 150, 0.8 + random() * 1.1]);
  for (let i = 0; i < 260; i++) {
    const side = random() < 0.5 ? -1 : 1;
    spots.push([side * (78 + random() * 140), 40 - random() * 210, 0.7 + random()]);
  }
  const mesh = new THREE.InstancedMesh(geometry, material, spots.length);
  const dummy = new THREE.Object3D();
  spots.forEach(([x, z, scale], index) => {
    dummy.position.set(x, terrainHeight(x, z) - 0.5, z);
    dummy.scale.set(scale, scale * (0.9 + random() * 0.6), scale);
    dummy.rotation.y = random() * Math.PI;
    dummy.updateMatrix();
    mesh.setMatrixAt(index, dummy.matrix);
  });
  mesh.instanceMatrix.needsUpdate = true;
  return mesh;
}

function buildSky(sunDir: THREE.Vector3) {
  const material = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: {
      uTop: { value: color(COLORS.skyTop) },
      uHorizon: { value: color(COLORS.skyHorizon) },
      uLime: { value: color(COLORS.row) },
      uViolet: { value: color(COLORS.route) },
      uSunDir: { value: sunDir },
    },
    vertexShader: /* glsl */ `
      varying vec3 vDir;
      void main() {
        vDir = normalize(position);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uTop, uHorizon, uLime, uViolet, uSunDir;
      varying vec3 vDir;
      float hash(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
      void main() {
        float h = clamp(vDir.y, -0.2, 1.0);
        vec3 color = mix(uHorizon, uTop, pow(max(h, 0.0), 0.55));
        float sun = max(dot(vDir, uSunDir), 0.0);
        color += uLime * pow(sun, 18.0) * 0.55 + vec3(1.0, 0.85, 0.55) * pow(sun, 300.0) * 3.0;
        color += uViolet * pow(1.0 - abs(vDir.x), 6.0) * smoothstep(0.35, 0.05, h) * 0.08;
        float star = step(0.9965, hash(floor(vDir * 380.0))) * smoothstep(0.12, 0.5, h);
        color += vec3(star) * 0.9;
        gl_FragColor = vec4(color, 1.0);
      }
    `,
  });
  return new THREE.Mesh(new THREE.SphereGeometry(820, 48, 24), material);
}

interface Drone {
  group: THREE.Group;
  craft: THREE.Group;
  rotors: THREE.Object3D[];
  leds: THREE.MeshBasicMaterial[];
  beam: THREE.Mesh;
}

function buildDrone(shared: Shared): Drone {
  const group = new THREE.Group();
  const shell = new THREE.MeshStandardMaterial({ color: COLORS.body, metalness: 0.65, roughness: 0.32 });
  const trim = new THREE.MeshStandardMaterial({ color: COLORS.row, emissive: color(COLORS.row, 1.6), roughness: 0.4 });
  const craft = new THREE.Group();
  craft.scale.setScalar(3.8);
  group.add(craft);

  craft.add(new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.18, 1.0), shell));
  const canopy = new THREE.Mesh(new THREE.SphereGeometry(0.3, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), shell);
  canopy.scale.set(1, 0.6, 1.35);
  canopy.position.y = 0.09;
  craft.add(canopy);
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.03, 0.12), trim);
  stripe.position.set(0, 0.02, 0.38);
  craft.add(stripe);

  const rotors: THREE.Object3D[] = [];
  const leds: THREE.MeshBasicMaterial[] = [];
  const disc = new THREE.MeshBasicMaterial({ color: COLORS.row, transparent: true, opacity: 0.12, depthWrite: false });
  const blade = new THREE.MeshStandardMaterial({ color: "#0b1210", roughness: 0.6 });
  for (const [sx, sz] of [
    [1, 1],
    [-1, 1],
    [1, -1],
    [-1, -1],
  ]) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.06, 0.95), shell);
    arm.position.set(sx * 0.42, 0.02, sz * 0.42);
    arm.rotation.y = sx * sz > 0 ? Math.PI / 4 : -Math.PI / 4;
    craft.add(arm);
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.1, 0.14, 12), shell);
    motor.position.set(sx * 0.72, 0.08, sz * 0.72);
    craft.add(motor);
    const rotor = new THREE.Group();
    rotor.position.set(sx * 0.72, 0.17, sz * 0.72);
    rotor.add(new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.012, 0.07), blade));
    const blur = new THREE.Mesh(new THREE.CircleGeometry(0.46, 28), disc);
    blur.rotation.x = -Math.PI / 2;
    rotor.add(blur);
    craft.add(rotor);
    rotors.push(rotor);
    const led = new THREE.MeshBasicMaterial({ color: color(sz > 0 ? COLORS.row : COLORS.route, 3) });
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.045, 8, 6), led);
    bulb.position.set(sx * 0.72, 0, sz * 0.72);
    craft.add(bulb);
    leds.push(led);
  }

  const gimbal = new THREE.Mesh(new THREE.SphereGeometry(0.12, 16, 12), shell);
  gimbal.position.set(0, -0.14, 0.25);
  craft.add(gimbal);
  const lens = new THREE.Mesh(new THREE.CircleGeometry(0.06, 16), new THREE.MeshBasicMaterial({ color: color(COLORS.row, 4) }));
  lens.position.set(0, -0.2, 0.33);
  lens.rotation.x = Math.PI / 2.4;
  craft.add(lens);

  const beamGeometry = new THREE.ConeGeometry(1, 1, 48, 1, true);
  beamGeometry.translate(0, -0.5, 0);
  const beam = new THREE.Mesh(
    beamGeometry,
    new THREE.ShaderMaterial({
      uniforms: { uTime: shared.uTime, uLime: shared.uLime },
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      vertexShader: PASS_VERTEX,
      fragmentShader: /* glsl */ `
        uniform float uTime;
        uniform vec3 uLime;
        varying vec2 vUv;
        void main() {
          float bands = smoothstep(0.86, 1.0, fract(vUv.y * 7.0 + uTime * 1.6));
          float edge = pow(abs(fract(vUv.x * 24.0) - 0.5) * 2.0, 18.0);
          float alpha = (0.07 + bands * 0.12 + edge * 0.05) * smoothstep(0.0, 0.25, vUv.y) * (0.35 + vUv.y * 0.65);
          gl_FragColor = vec4(uLime * alpha * 1.4, 1.0);
        }
      `,
    }),
  );
  group.add(beam);
  return { group, craft, rotors, leds, beam };
}

interface PathPoint {
  x: number;
  z: number;
  band: number;
  progress: number;
  turning: boolean;
}

/** Serpentine survey: straight passes across the rows, joined by half-circle turns outside the field. */
function surveyPath() {
  const margin = 5;
  const straight = FIELD.x1 - FIELD.x0 + margin * 2;
  const radius = BAND_WIDTH / 2;
  const turn = Math.PI * radius;
  const segment = straight + turn;
  const total = straight * FIELD.bands + turn * (FIELD.bands - 1);

  const at = (distance: number): PathPoint => {
    const d = Math.min(Math.max(distance, 0), total);
    const band = Math.min(FIELD.bands - 1, Math.floor(d / segment));
    const local = d - band * segment;
    const z = FIELD.zFar + (band + 0.5) * BAND_WIDTH;
    const forward = band % 2 === 0;
    const startX = forward ? FIELD.x0 - margin : FIELD.x1 + margin;
    const endX = forward ? FIELD.x1 + margin : FIELD.x0 - margin;
    if (local <= straight || band === FIELD.bands - 1) {
      const x = startX + (endX - startX) * Math.min(1, local / straight);
      const u = (x - FIELD.x0) / (FIELD.x1 - FIELD.x0);
      return { x, z, band, progress: Math.min(1, Math.max(0, forward ? u : 1 - u)), turning: false };
    }
    const angle = ((local - straight) / turn) * Math.PI;
    const side = forward ? 1 : -1;
    return { x: endX + side * Math.sin(angle) * radius, z: z + radius - Math.cos(angle) * radius, band, progress: 1, turning: true };
  };
  return { total, at, start: at(0), end: at(total) };
}

export function createVineyardScene(canvas: HTMLCanvasElement, options: SceneOptions): VineyardScene {
  const random = rng(311);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.6));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.3;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(COLORS.fog, 0.0058);
  const camera = new THREE.PerspectiveCamera(44, 1, 0.5, 1800);

  const sunDir = new THREE.Vector3(-0.55, 0.34, -0.77).normalize();
  const shared = sharedUniforms(sunDir);

  const waste: Marker[] = Array.from({ length: 7 }, () => {
    const row = Math.floor(random() * (ROW_COUNT - 1));
    return { x: rowX(row) + FIELD.rowSpacing / 2, z: FIELD.zFar + 6 + random() * (FIELD.zNear - FIELD.zFar - 12), found: false };
  });
  const gaps = Array.from({ length: 5 }, () => {
    const z = FIELD.zFar + 8 + random() * (FIELD.zNear - FIELD.zFar - 24);
    return { x: rowX(2 + Math.floor(random() * (ROW_COUNT - 4))), z, z1: z + 5 + random() * 4, found: false };
  });
  const routePoints = planRoute();

  const { front, placement, posts, frontVines } = placeVines(random, gaps);
  scene.add(buildSky(sunDir));
  const terrain = buildTerrain(shared, gaps);
  scene.add(terrain);
  scene.add(buildVines(shared, placement));
  scene.add(buildCanopyOutlines(shared, placement.centres));
  scene.add(buildPosts(posts));
  scene.add(buildRowAxes(shared, gaps));
  const route = buildRoute(shared, routePoints);
  scene.add(route.mesh);
  const startMarker = buildStartMarker(routePoints[0]);
  scene.add(startMarker.group);
  scene.add(buildTrees(random));
  scene.add(new THREE.HemisphereLight("#8fd6c8", "#12301d", 0.9));
  const sun = new THREE.DirectionalLight(COLORS.sun, 2.2);
  sun.position.copy(sunDir).multiplyScalar(100);
  scene.add(sun);

  const drone = buildDrone(shared);
  scene.add(drone.group);
  const wasteBoxes = buildWaste(random, waste);
  wasteBoxes.forEach(({ group }) => scene.add(group));
  const beams = buildBeams(waste, COLORS.waste);
  beams.forEach(({ mesh }) => scene.add(mesh));

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.65, 0.5, 0.7);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  const path = surveyPath();
  const gapUniforms = (terrain.material as THREE.ShaderMaterial).uniforms.uGaps.value as THREE.Vector4[];
  const pointer = new THREE.Vector2();
  const pointerSmooth = new THREE.Vector2();
  const lookTarget = new THREE.Vector3(0, 17, -60);
  const lookGoal = new THREE.Vector3();
  const projected = new THREE.Vector3();
  const position = new THREE.Vector3();
  const returnFrom = new THREE.Vector3();

  let phase: SurveyPhase = "scanning";
  let distance = path.total * 0.18;
  let phaseTime = 0;
  let intensity = 1;
  let routeProgress = 0;
  let heading = 0;
  let bank = 0;
  let time = 0;
  let raf = 0;
  let running = false;
  let ready = false;
  let lastTelemetry = -1;
  let rowsDetected = 0;
  let previousX = 0;
  let previousZ = 0;
  let lastFrame = 0;

  const surveyDone = () => phase === "complete" || phase === "routing";

  function dronePoint(): PathPoint {
    if (surveyDone()) {
      const p = path.end;
      position.set(p.x, terrainHeight(p.x, p.z) + ALTITUDE + Math.min(phaseTime + (phase === "routing" ? HOLD_S : 0), 1.5) * 3, p.z);
      return p;
    }
    if (phase === "returning") {
      const t = smooth(0, 1, phaseTime / RETURN_S);
      const { start } = path;
      const x = returnFrom.x + (start.x - returnFrom.x) * t;
      const z = returnFrom.z + (start.z - returnFrom.z) * t;
      position.set(x, terrainHeight(x, z) + ALTITUDE + 4.5 * (1 - t) + Math.sin(t * Math.PI) * 12, z);
      return { ...start, progress: 0 };
    }
    const p = path.at(distance);
    position.set(p.x, terrainHeight(p.x, p.z) + ALTITUDE, p.z);
    return p;
  }

  function advance(dt: number) {
    phaseTime += dt;
    if (phase === "scanning" || phase === "turning") {
      distance += SPEED * dt;
      if (distance >= path.total) {
        phase = "complete";
        phaseTime = 0;
      }
    } else if (phase === "complete" && phaseTime > HOLD_S) {
      phase = "routing";
      phaseTime = 0;
    } else if (phase === "routing" && phaseTime > ROUTE_DRAW_S + ROUTE_HOLD_S) {
      phase = "returning";
      phaseTime = 0;
      returnFrom.copy(drone.group.position);
    } else if (phase === "returning" && phaseTime > RETURN_S) {
      phase = "scanning";
      phaseTime = 0;
      distance = 0;
      rowsDetected = 0;
      for (const marker of [...waste, ...gaps]) marker.found = false;
    }
  }

  function step(dt: number) {
    time += dt;
    advance(dt);
    const point = dronePoint();
    if (phase === "scanning" || phase === "turning") phase = point.turning ? "turning" : "scanning";
    intensity = phase === "returning" ? Math.max(0, 1 - phaseTime / 1.4) : 1;
    routeProgress = phase === "routing" ? smooth(0, 1, phaseTime / ROUTE_DRAW_S) : phase === "returning" ? 1 : 0;

    const vx = position.x - previousX;
    const vz = position.z - previousZ;
    previousX = position.x;
    previousZ = position.z;
    if (Math.hypot(vx, vz) > 1e-3) {
      let delta = Math.atan2(vx, vz) - heading;
      delta = Math.atan2(Math.sin(delta), Math.cos(delta));
      heading += delta * Math.min(1, dt * 6);
      bank += (-delta * 2.2 - bank) * Math.min(1, dt * 4);
    } else {
      bank *= 1 - Math.min(1, dt * 3);
    }

    drone.group.position.copy(position);
    drone.group.position.y += Math.sin(time * 2.1) * 0.25;
    drone.group.rotation.set(0, heading, 0);
    drone.craft.rotation.set(0.12, 0, THREE.MathUtils.clamp(bank, -0.5, 0.5));
    drone.rotors.forEach((rotor, index) => (rotor.rotation.y += dt * (index % 2 ? -46 : 46)));
    const blink = Math.sin(time * 6) > 0.6 ? 1 : 0.25;
    drone.leds.forEach((led, index) => led.color.copy(color(index < 2 ? COLORS.row : COLORS.route, 0.6 + 2.6 * blink)));

    const ground = terrainHeight(position.x, position.z);
    const height = Math.max(1, drone.group.position.y - ground);
    const scanning = phase === "scanning" || phase === "turning";
    // GLSL smoothstep is undefined for equal edges, so "no footprint" is a tiny one.
    const radius = scanning ? FOOTPRINT : 0.001;
    drone.beam.visible = scanning;
    drone.beam.scale.set(FOOTPRINT / 2.1, height / 2.1, FOOTPRINT / 2.1);

    shared.uTime.value = time;
    shared.uDrone.value.set(position.x, ground, position.z);
    shared.uFootprint.value = radius;
    const scanBand = scanning ? point.band : FIELD.bands;
    shared.uScan.value.set(scanBand, point.progress, intensity, 0);
    route.uRoute.value.set(routeProgress, phase === "returning" ? intensity : routeProgress > 0 ? 1 : 0);

    startMarker.group.visible = phase === "routing" || (phase === "returning" && intensity > 0);
    const ping = (time * 0.8) % 1;
    startMarker.ping.scale.setScalar(1 + ping * 1.6);
    (startMarker.ping.material as THREE.MeshBasicMaterial).opacity = 1 - ping;

    if (scanning && point.band === 0) rowsDetected = Math.max(rowsDetected, Math.floor(point.progress * ROW_COUNT));
    else if (point.band > 0 || !scanning) rowsDetected = phase === "returning" ? rowsDetected : ROW_COUNT;
    for (const marker of [...waste, ...gaps]) {
      if (!marker.found && (surveyDone() || (scanning && scannedAt(marker.x, marker.z, point.band, point.progress)))) marker.found = true;
    }
    gapUniforms.forEach((v, i) => (v.w = gaps[i].found ? intensity : 0));
    const ease = Math.min(1, dt * 5);
    wasteBoxes.forEach(({ box, marker }) => {
      const target = marker.found ? Math.max(0.001, intensity) : 0.001;
      box.scale.setScalar(box.scale.x + (target - box.scale.x) * ease);
      box.rotation.y = Math.sin(time * 0.8 + marker.x) * 0.05;
    });
    beams.forEach(({ material, marker }) => {
      const target = marker.found ? intensity : 0;
      material.uniforms.uOpacity.value += (target - material.uniforms.uOpacity.value) * Math.min(1, dt * 3);
      material.uniforms.uTime.value = time;
    });

    pointerSmooth.lerp(pointer, Math.min(1, dt * 2.5));
    const narrow = camera.aspect < 1;
    camera.position.set(
      Math.sin(time * 0.05) * 6 + pointerSmooth.x * 7,
      (narrow ? 52 : 40) - pointerSmooth.y * 3,
      narrow ? 120 : 84,
    );
    lookGoal.set(position.x * 0.18, 17, -60 + (position.z + 38) * 0.1);
    lookTarget.lerp(lookGoal, Math.min(1, dt * 1.5));
    camera.lookAt(lookTarget);

    if (time - lastTelemetry > 0.1) {
      lastTelemetry = time;
      const coverage = surveyDone() ? 1 : phase === "returning" ? intensity : (point.band + point.progress) / FIELD.bands;
      options.onTelemetry({
        phase,
        band: point.band,
        bands: FIELD.bands,
        coverage,
        rowsDetected,
        vinesAnalysed: Math.round(coverage * front),
        vinesTotal: front,
        waste: waste.map((marker) => ({ ...marker })),
        gaps: gaps.map((marker) => ({ ...marker })),
        routeProgress,
        routeLengthM: route.length,
        altitude: height,
        speedKmh: phase === "complete" || phase === "routing" ? 0 : SPEED * 3.6,
        lat: ORIGIN.lat - position.z / 111_320,
        lon: ORIGIN.lon + position.x / (111_320 * Math.cos((ORIGIN.lat * Math.PI) / 180)),
        drone: { x: position.x, z: position.z, heading },
        scan: { band: scanBand, progress: point.progress, intensity },
      });
    }
  }

  function render() {
    composer.render();
    projected.copy(drone.group.position).project(camera);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const visible = projected.z < 1 && Math.abs(projected.x) < 1.1 && Math.abs(projected.y) < 1.1;
    options.onDroneScreen(((projected.x + 1) / 2) * w, ((1 - projected.y) / 2) * h, visible);
    if (!ready) {
      ready = true;
      options.onReady();
    }
  }

  function loop(now: number) {
    raf = requestAnimationFrame(loop);
    const dt = lastFrame ? Math.min((now - lastFrame) / 1000, 1 / 20) : 0;
    lastFrame = now;
    step(dt);
    render();
  }

  function resize() {
    const w = canvas.clientWidth || 1;
    const h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.resolution.set(w / 2, h / 2);
    camera.aspect = w / h;
    camera.fov = camera.aspect < 1 ? 62 : 44;
    camera.updateProjectionMatrix();
    if (options.still) {
      step(0);
      render();
    }
  }

  resize();
  if (options.still) {
    // A frame after the survey, with the route drawn: every annotation layer visible at once.
    distance = path.total;
    for (let i = 0; i < 60 * (HOLD_S + ROUTE_DRAW_S + 0.5); i++) step(1 / 60);
    render();
  }

  const layout: SceneLayout = {
    rowXs: Array.from({ length: ROW_COUNT }, (_, i) => rowX(i)),
    vines: frontVines,
    route: routePoints,
    waste,
    gaps,
  };

  return {
    layout,
    resize,
    setPointer(x, y) {
      pointer.set(x, y);
    },
    setRunning(next) {
      if (options.still || next === running) return;
      running = next;
      if (running) {
        lastFrame = 0;
        raf = requestAnimationFrame(loop);
      } else {
        cancelAnimationFrame(raf);
      }
    },
    dispose() {
      cancelAnimationFrame(raf);
      running = false;
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) material.forEach((m) => m.dispose());
        else material?.dispose();
      });
      composer.dispose();
      renderer.dispose();
    },
  };
}
