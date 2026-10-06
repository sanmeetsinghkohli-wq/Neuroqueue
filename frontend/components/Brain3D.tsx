"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

/**
 * Procedural point-cloud brain: two wrinkled hemispheres, a cerebellum and a
 * brainstem, with a scan plane sweeping through and one region glowing as the
 * plane passes (the "flagged for a radiologist" moment). Decorative only.
 */
const VERT = /* glsl */ `
  uniform float uTime;
  uniform float uScan;
  uniform vec3 uHot;
  attribute float aSeed;
  varying float vScan;
  varying float vHot;
  varying float vDepth;
  void main() {
    vec3 p = position;
    p += normalize(position) * sin(uTime * 1.3 + aSeed * 40.0) * 0.012;
    float d = abs(p.y - uScan);
    vScan = smoothstep(0.07, 0.0, d);
    float h = distance(p, uHot);
    vHot = smoothstep(0.55, 0.0, h) * (0.55 + 0.45 * sin(uTime * 3.0));
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vDepth = clamp((-mv.z - 2.2) / 2.6, 0.0, 1.0);
    gl_PointSize = (1.6 + aSeed * 1.8 + vScan * 1.6 + vHot * 3.5) * (6.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;
const FRAG = /* glsl */ `
  varying float vScan;
  varying float vHot;
  varying float vDepth;
  void main() {
    float r = length(gl_PointCoord - 0.5);
    if (r > 0.5) discard;
    float a = smoothstep(0.5, 0.05, r);
    vec3 base = mix(vec3(0.35, 0.78, 1.0), vec3(0.42, 0.45, 0.98), vDepth);
    vec3 col = mix(base, vec3(0.75, 0.97, 1.0), vScan);
    col = mix(col, vec3(1.0, 0.36, 0.22), vHot);
    gl_FragColor = vec4(col, a * (0.28 + 0.5 * (1.0 - vDepth) + vScan * 0.35 + vHot * 0.8));
  }
`;

function buildBrain(count: number) {
  const pos = new Float32Array(count * 3);
  const seed = new Float32Array(count);
  let i = 0;
  // deterministic pseudo-random so server and client agree
  let s = 1337;
  const rnd = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
  const put = (x: number, y: number, z: number) => { pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z; seed[i] = rnd(); i++; };

  const cerebrum = Math.floor(count * 0.84);
  while (i < cerebrum) {
    const u = rnd() * 2 - 1, t = rnd() * Math.PI * 2, q = Math.sqrt(1 - u * u);
    let x = q * Math.cos(t), y = u, z = q * Math.sin(t);
    if (y < -0.72) continue;                                    // flat underside
    const gyri = 0.06 * Math.sin(9 * x + 4 * y) * Math.sin(8 * z + 3 * x) + 0.04 * Math.sin(15 * y + 6 * z);
    const r = 1 + gyri - 0.05 * rnd();
    x *= r * 0.86; y *= r * 0.82; z *= r * 1.12;
    const fissure = Math.exp(-(x * x) / 0.012) * (y > -0.1 ? 0.16 : 0.05);   // split between hemispheres
    y -= fissure;
    x += Math.sign(x || 1) * 0.035;
    put(x, y + 0.12, z);
  }
  const cerebellum = Math.floor(count * 0.96);
  while (i < cerebellum) {
    const u = rnd() * 2 - 1, t = rnd() * Math.PI * 2, q = Math.sqrt(1 - u * u);
    const ridge = 1 + 0.05 * Math.sin(26 * u);
    put(q * Math.cos(t) * 0.5 * ridge, u * 0.3 * ridge - 0.52, q * Math.sin(t) * 0.36 * ridge - 0.72);
  }
  while (i < count) {
    const t = rnd() * Math.PI * 2, h = rnd();
    put(Math.cos(t) * 0.13, -0.5 - h * 0.38, Math.sin(t) * 0.13 - 0.34 + h * 0.1);
  }
  return { pos, seed };
}

function Points({ count }: { count: number }) {
  const group = useRef<THREE.Group>(null);
  const mat = useRef<THREE.ShaderMaterial>(null);
  const { pos, seed } = useMemo(() => buildBrain(count), [count]);
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uScan: { value: 0 }, uHot: { value: new THREE.Vector3(0.42, 0.42, 0.25) } }), []);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (mat.current) {
      mat.current.uniforms.uTime.value = t;
      mat.current.uniforms.uScan.value = Math.sin(t * 0.7) * 1.05;
    }
    if (group.current) {
      group.current.rotation.y = t * 0.16 + state.pointer.x * 0.5;
      group.current.rotation.x = THREE.MathUtils.lerp(group.current.rotation.x, -0.08 + state.pointer.y * -0.25, 0.05);
    }
  });

  return (
    <group ref={group}>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[pos, 3]} />
          <bufferAttribute attach="attributes-aSeed" args={[seed, 1]} />
        </bufferGeometry>
        <shaderMaterial ref={mat} vertexShader={VERT} fragmentShader={FRAG} uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
      </points>
    </group>
  );
}

export default function Brain3D({ className }: { className?: string }) {
  return (
    <div className={className} aria-hidden>
      <Canvas camera={{ position: [0, 0, 3.3], fov: 42 }} dpr={[1, 1.8]} gl={{ antialias: true, alpha: true }}>
        <Points count={15000} />
      </Canvas>
    </div>
  );
}
