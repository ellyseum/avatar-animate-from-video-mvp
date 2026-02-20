import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, useGLTF, Environment, MeshReflectorMaterial } from '@react-three/drei';
import {
  AnimationMixer, Box3, FrontSide, RepeatWrapping, CanvasTexture,
  MeshPhysicalMaterial, SRGBColorSpace,
} from 'three';
import { Play, Pause, RotateCcw } from 'lucide-react';

// ---------------------------------------------------------------------------
// Procedural textures
// ---------------------------------------------------------------------------

function makeWallTexture(size = 512) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#2a2a2f';
  ctx.fillRect(0, 0, size, size);
  const imgData = ctx.getImageData(0, 0, size, size);
  for (let i = 0; i < imgData.data.length; i += 4) {
    const n = (Math.random() - 0.5) * 12;
    imgData.data[i] += n;
    imgData.data[i + 1] += n;
    imgData.data[i + 2] += n;
  }
  ctx.putImageData(imgData, 0, 0);
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth = 1;
  for (let y = 0; y < size; y += 64) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size, y); ctx.stroke();
  }
  for (let x = 0; x < size; x += 128) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size); ctx.stroke();
  }
  const tex = new CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = RepeatWrapping;
  tex.repeat.set(2, 2);
  tex.colorSpace = SRGBColorSpace;
  return tex;
}

// ---------------------------------------------------------------------------
// Mirror panel (planar reflection)
// ---------------------------------------------------------------------------

function Mirror({ position, rotation, width, height }: {
  position: [number, number, number];
  rotation: [number, number, number];
  width: number;
  height: number;
}) {
  return (
    <mesh position={position} rotation={rotation}>
      <planeGeometry args={[width, height]} />
      <MeshReflectorMaterial
        resolution={2048}
        mirror={1}
        mixBlur={0}
        mixStrength={10}
        blur={[0, 0]}
        color="#ffffff"
        metalness={1}
        roughness={0}
        depthScale={0}
      />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Room: 4 walls + floor (no ceiling — HDR sky visible above)
// ---------------------------------------------------------------------------

function Room() {
  const wallTex = useMemo(() => makeWallTexture(), []);

  const W = 8;
  const H = 4;
  const D = 8;
  const mirrorW = 1.8;
  const mirrorH = H - 0.2;
  const mirrorInset = 0.01;

  return (
    <group>
      <mesh position={[0, H / 2, -D / 2]} receiveShadow>
        <planeGeometry args={[W, H]} />
        <meshStandardMaterial map={wallTex} roughness={0.85} side={FrontSide} />
      </mesh>
      <mesh position={[0, H / 2, D / 2]} rotation={[0, Math.PI, 0]} receiveShadow>
        <planeGeometry args={[W, H]} />
        <meshStandardMaterial map={wallTex} roughness={0.85} side={FrontSide} />
      </mesh>
      <mesh position={[-W / 2, H / 2, 0]} rotation={[0, Math.PI / 2, 0]} receiveShadow>
        <planeGeometry args={[D, H]} />
        <meshStandardMaterial map={wallTex} roughness={0.85} side={FrontSide} />
      </mesh>
      <mesh position={[W / 2, H / 2, 0]} rotation={[0, -Math.PI / 2, 0]} receiveShadow>
        <planeGeometry args={[D, H]} />
        <meshStandardMaterial map={wallTex} roughness={0.85} side={FrontSide} />
      </mesh>

      <Mirror position={[0, mirrorH / 2 + 0.1, -D / 2 + mirrorInset]} rotation={[0, 0, 0]} width={mirrorW} height={mirrorH} />
      <Mirror position={[0, mirrorH / 2 + 0.1, D / 2 - mirrorInset]} rotation={[0, Math.PI, 0]} width={mirrorW} height={mirrorH} />
      <Mirror position={[-W / 2 + mirrorInset, mirrorH / 2 + 0.1, 0]} rotation={[0, Math.PI / 2, 0]} width={mirrorW} height={mirrorH} />
      <Mirror position={[W / 2 - mirrorInset, mirrorH / 2 + 0.1, 0]} rotation={[0, -Math.PI / 2, 0]} width={mirrorW} height={mirrorH} />

      <pointLight position={[0, H - 0.5, -D / 2 + 0.3]} intensity={3} distance={6} color="#e8e0d8" castShadow />
      <pointLight position={[0, H - 0.5, D / 2 - 0.3]} intensity={3} distance={6} color="#e8e0d8" castShadow />
      <pointLight position={[-W / 2 + 0.3, H - 0.5, 0]} intensity={3} distance={6} color="#e8e0d8" castShadow />
      <pointLight position={[W / 2 - 0.3, H - 0.5, 0]} intensity={3} distance={6} color="#e8e0d8" castShadow />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Model (animated GLB)
// ---------------------------------------------------------------------------

interface ModelHandle {
  seek: (time: number) => void;
}

interface ModelProps {
  url: string;
  playing: boolean;
  speed: number;
  onTimeUpdate: (time: number) => void;
  onDurationReady: (duration: number) => void;
}

const Model = forwardRef<ModelHandle, ModelProps>(
  ({ url, playing, speed, onTimeUpdate, onDurationReady }, ref) => {
    const gltf = useGLTF(url);
    const mixerRef = useRef<AnimationMixer | null>(null);
    const durationRef = useRef(0);
    const lastReportRef = useRef(0);

    const clip = useMemo(() => {
      if (!gltf.animations.length) return null;
      return gltf.animations.reduce((best, c) =>
        c.tracks.length > best.tracks.length ? c : best
      );
    }, [gltf.animations]);

    const yOffset = useMemo(() => {
      const box = new Box3().setFromObject(gltf.scene);
      return -box.min.y;
    }, [gltf.scene]);

    // Detect if GLB has real textures (Mixamo character) or is untextured (SMPL)
    const hasTextures = useMemo(() => {
      let found = false;
      gltf.scene.traverse((child: any) => {
        if (!child.isMesh || found) return;
        const mat = child.material;
        if (mat && (mat.map || mat.normalMap || mat.emissiveMap || mat.aoMap)) {
          found = true;
        }
      });
      return found;
    }, [gltf.scene]);

    // Apply materials: keep originals for textured models, teal for SMPL
    useEffect(() => {
      gltf.scene.traverse((child: any) => {
        if (!child.isMesh) return;
        child.castShadow = true;
        child.receiveShadow = true;

        if (hasTextures) {
          if (child.material) {
            child.material.envMapIntensity = 0.8;
          }
        } else {
          const mat = new MeshPhysicalMaterial({
            color: '#45b8b0',
            roughness: 0.35,
            metalness: 0.08,
            clearcoat: 0.4,
            clearcoatRoughness: 0.3,
            envMapIntensity: 1.2,
          });

          mat.onBeforeCompile = (shader) => {
            shader.fragmentShader = shader.fragmentShader.replace(
              '#include <emissivemap_fragment>',
              `#include <emissivemap_fragment>
              vec3 viewDir = normalize(vViewPosition);
              vec3 worldNormal = normalize((vec4(normal, 0.0) * viewMatrix).xyz);
              float fresnel = pow(1.0 - abs(dot(worldNormal, viewDir)), 3.0);
              totalEmissiveRadiance += vec3(0.3, 0.8, 0.75) * fresnel * 0.5;`
            );
          };

          child.material = mat;
        }
      });
    }, [gltf.scene, hasTextures]);

    useEffect(() => {
      if (!clip) return;
      const mixer = new AnimationMixer(gltf.scene);
      const action = mixer.clipAction(clip);
      action.play();
      mixerRef.current = mixer;
      durationRef.current = clip.duration;
      onDurationReady(clip.duration);
      return () => { mixer.stopAllAction(); mixer.uncacheRoot(gltf.scene); };
    }, [clip, gltf.scene, onDurationReady]);

    useEffect(() => {
      if (mixerRef.current) mixerRef.current.timeScale = playing ? speed : 0;
    }, [playing, speed]);

    useImperativeHandle(ref, () => ({
      seek: (time: number) => {
        if (!mixerRef.current) return;
        const prevScale = mixerRef.current.timeScale;
        mixerRef.current.timeScale = 1;
        mixerRef.current.setTime(time);
        mixerRef.current.timeScale = prevScale;
        lastReportRef.current = time;
        onTimeUpdate(time);
      },
    }), [onTimeUpdate]);

    useFrame((_, delta) => {
      if (!mixerRef.current) return;
      mixerRef.current.update(delta);
      const t = mixerRef.current.time % (durationRef.current || 1);
      if (Math.abs(t - lastReportRef.current) > 0.06) {
        lastReportRef.current = t;
        onTimeUpdate(t);
      }
    });

    return (
      <group position={[0, yOffset, 0]}>
        <primitive object={gltf.scene} />
      </group>
    );
  }
);

// ---------------------------------------------------------------------------
// Viewer wrapper
// ---------------------------------------------------------------------------

export function ModelViewer({ glbUrl, scene = true }: { glbUrl: string; scene?: boolean }) {
  const modelRef = useRef<ModelHandle>(null);
  const [playing, setPlaying] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);

  const togglePlay = useCallback(() => setPlaying(p => !p), []);
  const handleSeek = useCallback((t: number) => { modelRef.current?.seek(t); setTime(t); }, []);
  const handleRestart = useCallback(() => { modelRef.current?.seek(0); setTime(0); setPlaying(true); }, []);
  const handleSpeedChange = useCallback((s: number) => setSpeed(s), []);
  const handleDuration = useCallback((d: number) => setDuration(d), []);
  const handleTimeUpdate = useCallback((t: number) => setTime(t), []);

  return (
    <div className="w-full">
      <div className="bg-[var(--color-surface)] rounded-lg border border-[var(--color-border)] overflow-hidden">
        <div className="w-full aspect-[4/3]">
          <Canvas
            shadows={scene}
            camera={{ position: [0, 1.2, 4], fov: 45 }}
            gl={{ antialias: true, ...(scene ? { toneMappingExposure: 0.9 } : {}) }}
          >
            {scene ? (
              <>
                <Environment
                  preset="warehouse"
                  background
                  backgroundBlurriness={0.05}
                  environmentIntensity={0.6}
                />
                <ambientLight intensity={0.1} />
                <directionalLight
                  position={[1, 5, 2]}
                  intensity={0.5}
                  castShadow
                  shadow-mapSize-width={2048}
                  shadow-mapSize-height={2048}
                  shadow-camera-near={0.5}
                  shadow-camera-far={15}
                  shadow-camera-left={-5}
                  shadow-camera-right={5}
                  shadow-camera-top={5}
                  shadow-camera-bottom={-5}
                  shadow-bias={-0.001}
                />
                <directionalLight
                  position={[-1, 5, -2]}
                  intensity={0.3}
                  castShadow
                  shadow-mapSize-width={1024}
                  shadow-mapSize-height={1024}
                  shadow-camera-near={0.5}
                  shadow-camera-far={15}
                  shadow-camera-left={-5}
                  shadow-camera-right={5}
                  shadow-camera-top={5}
                  shadow-camera-bottom={-5}
                />
                <directionalLight position={[0.5, -3, 1]} intensity={0.1} />
                <Room />
              </>
            ) : (
              <>
                <ambientLight intensity={0.6} />
                <directionalLight position={[2, 4, 3]} intensity={0.8} />
                <directionalLight position={[-1, 3, -2]} intensity={0.3} />
              </>
            )}

            <Model
              ref={modelRef}
              url={glbUrl}
              playing={playing}
              speed={speed}
              onTimeUpdate={handleTimeUpdate}
              onDurationReady={handleDuration}
            />

            <OrbitControls
              target={[0, 0.9, 0]}
              minDistance={1.5}
              maxDistance={8}
              maxPolarAngle={Math.PI / 2 + 0.1}
            />
          </Canvas>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-4 px-4 py-3 border-t border-[var(--color-border)]">
          <button
            onClick={togglePlay}
            className="p-2 rounded hover:bg-[var(--color-surface-2)] transition-colors"
          >
            {playing
              ? <Pause size={18} className="text-[var(--color-text)]" />
              : <Play size={18} className="text-[var(--color-text)]" />
            }
          </button>

          <button
            onClick={handleRestart}
            className="p-2 rounded hover:bg-[var(--color-surface-2)] transition-colors"
          >
            <RotateCcw size={16} className="text-[var(--color-text)]" />
          </button>

          <input
            type="range"
            min={0}
            max={duration || 1}
            step={0.01}
            value={time}
            onChange={(e) => handleSeek(parseFloat(e.target.value))}
            className="flex-1 accent-[var(--color-primary)]"
          />

          <span className="text-xs text-[var(--color-text-muted)] tabular-nums w-32 text-right">
            F{Math.round(time * 30)} &middot; {time.toFixed(1)}s / {duration.toFixed(1)}s
          </span>

          <select
            value={speed}
            onChange={(e) => handleSpeedChange(parseFloat(e.target.value))}
            className="text-xs bg-[var(--color-surface-2)] border border-[var(--color-border)] rounded px-2 py-1 text-[var(--color-text)]"
          >
            {[0.25, 0.5, 1, 1.5, 2].map(s => (
              <option key={s} value={s}>{s}x</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
