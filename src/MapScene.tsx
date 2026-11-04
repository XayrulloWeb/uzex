import { useEffect, useMemo, useRef, useState, Component, type ReactNode } from 'react';
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import * as THREE from 'three';
import type { Lang, Region, RegionStat, Route } from './types';

type Props = {
  regions: Region[];
  stats: RegionStat[];
  routes: Route[];
  selected: string;
  lang: Lang;
  onSelect: (id: string) => void;
  reduced: boolean;
  flat?: boolean;
};
type Feature = {
  properties: { id: string };
  geometry: { type: string; coordinates: number[][][][] };
};
type Geometry = { features: Feature[] };
const vector = (lng: number, lat: number, height = 0.45) =>
  new THREE.Vector3((lng - 64.8) * 1.8, height, -(lat - 41.2) * 2.25);

function Controls() {
  const { camera, gl, size, invalidate } = useThree();
  const controls = useRef<OrbitControls | null>(null);
  useEffect(() => {
    const instance = new OrbitControls(camera, gl.domElement);
    instance.enableDamping = true;
    instance.enablePan = false;
    instance.enableZoom = false;
    instance.minPolarAngle = 0.35;
    instance.maxPolarAngle = Math.PI / 2.6;
    instance.minAzimuthAngle = -0.35;
    instance.maxAzimuthAngle = 0.35;
    instance.target.set(0, 0, 0);
    instance.update();
    instance.addEventListener('change', () => invalidate());
    controls.current = instance;
    return () => instance.dispose();
  }, [camera, gl, invalidate]);
  useEffect(() => {
    if (camera instanceof THREE.OrthographicCamera) {
      camera.zoom = Math.min(size.width / 38, size.height / 24);
      camera.updateProjectionMatrix();
    }
  }, [camera, size]);
  useFrame(() => controls.current?.update());
  return null;
}

function RegionShape({
  feature,
  active,
  selected,
  weight,
  onHover,
  onSelect,
}: {
  feature: Feature;
  active: boolean;
  selected: boolean;
  weight: number;
  onHover: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const { geometry, edges } = useMemo(() => {
    const shapes = feature.geometry.coordinates.map((rings) => {
      const shape = new THREE.Shape();
      rings.forEach((points, index) => {
        const path = index === 0 ? shape : new THREE.Path();
        points.forEach(([lng, lat], i) => {
          const p = vector(lng, lat);
          if (i === 0) path.moveTo(p.x, -p.z);
          else path.lineTo(p.x, -p.z);
        });
        if (index > 0) shape.holes.push(path);
      });
      return shape;
    });
    const geometry = new THREE.ExtrudeGeometry(shapes, {
      depth: 0.5,
      bevelEnabled: true,
      bevelSize: 0.015,
      bevelThickness: 0.025,
      bevelSegments: 1,
      steps: 1,
    });
    geometry.rotateX(-Math.PI / 2);
    const edges = new THREE.EdgesGeometry(geometry, 25);
    return { geometry, edges };
  }, [feature]);
  useEffect(
    () => () => {
      geometry.dispose();
      edges.dispose();
    },
    [geometry, edges],
  );
  const color =
    selected || active
      ? '#b5ce8b'
      : new THREE.Color('#3d5038').lerp(
          new THREE.Color('#829265'),
          0.23 + Math.sqrt(weight) * 0.67,
        );
  return (
    <group>
      <mesh
        geometry={geometry}
        onPointerOver={(e) => {
          e.stopPropagation();
          onHover(feature.properties.id);
          document.body.style.cursor = 'pointer';
        }}
        onPointerOut={() => {
          onHover('');
          document.body.style.cursor = '';
        }}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(feature.properties.id);
        }}
      >
        <meshStandardMaterial color={color} metalness={0.15} roughness={0.7} />
      </mesh>
      <lineSegments geometry={edges}>
        <lineBasicMaterial
          color={selected || active ? '#edffb6' : '#a0ba7d'}
          transparent
          opacity={selected || active ? 0.85 : 0.3}
        />
      </lineSegments>
    </group>
  );
}

function GroundGrid() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.1, 0]}>
      <planeGeometry args={[44, 32]} />
      <shaderMaterial
        transparent
        depthWrite={false}
        vertexShader={`varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`}
        fragmentShader={`varying vec2 vUv;void main(){vec2 p=vUv*32.0;vec2 g=abs(fract(p-0.5)-0.5)/fwidth(p);float line=1.0-min(min(g.x,g.y),1.0);float fade=1.0-smoothstep(0.12,0.58,length((vUv-0.5)*vec2(1.0,0.85)));gl_FragColor=vec4(0.42,0.52,0.31,line*fade*0.27);}`}
      />
    </mesh>
  );
}

function Flow({
  origin,
  destination,
  index,
  reduced,
}: {
  origin: Region;
  destination: Region;
  index: number;
  reduced: boolean;
}) {
  const particle = useRef<THREE.Mesh>(null);
  const { curve, line } = useMemo(() => {
    const a = vector(origin.lng, origin.lat, 0.7),
      b = vector(destination.lng, destination.lat, 0.7);
    const middle = a.clone().add(b).multiplyScalar(0.5);
    middle.y += Math.min(5, a.distanceTo(b) * 0.28 + 1);
    const curve = new THREE.QuadraticBezierCurve3(a, middle, b);
    return {
      curve,
      line: new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)),
        new THREE.LineBasicMaterial({
          color: '#d4ef8a',
          transparent: true,
          opacity: 0.13 + (index % 3) * 0.035,
        }),
      ),
    };
  }, [origin, destination, index]);
  useEffect(
    () => () => {
      line.geometry.dispose();
      (line.material as THREE.Material).dispose();
    },
    [line],
  );
  useFrame(({ clock }) => {
    if (particle.current)
      particle.current.position.copy(
        curve.getPoint(reduced ? 0.55 : (clock.elapsedTime * 0.12 + index * 0.08) % 1),
      );
  });
  return (
    <group>
      <primitive object={line} />
      <mesh ref={particle}>
        <sphereGeometry args={[0.055, 8, 8]} />
        <meshBasicMaterial color="#ebffb9" />
      </mesh>
    </group>
  );
}

function Node({
  region,
  active,
  selected,
  weight,
  onHover,
  onSelect,
}: {
  region: Region;
  active: boolean;
  selected: boolean;
  weight: number;
  onHover: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const ref = useRef<THREE.Mesh>(null);
  const pos = useMemo(() => vector(region.lng, region.lat, 0.67), [region]);
  const radius = 0.12 + Math.sqrt(weight) * 0.2;
  function enter(e: ThreeEvent<PointerEvent>) {
    e.stopPropagation();
    onHover(region.id);
    document.body.style.cursor = 'pointer';
  }
  function leave() {
    onHover('');
    document.body.style.cursor = '';
  }
  useEffect(
    () => () => {
      document.body.style.cursor = '';
    },
    [],
  );
  return (
    <group position={pos}>
      <mesh
        ref={ref}
        onPointerOver={enter}
        onPointerOut={leave}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(region.id);
        }}
      >
        <sphereGeometry args={[Math.max(0.24, radius * 1.5), 12, 12]} />
        <meshBasicMaterial transparent opacity={0} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[radius * 1.5, radius * 1.7, 32]} />
        <meshBasicMaterial
          color={selected ? '#ffffff' : '#d5f598'}
          side={THREE.DoubleSide}
          transparent
          opacity={active || selected ? 0.9 : 0.3}
        />
      </mesh>
      <mesh>
        <sphereGeometry args={[active || selected ? radius * 1.25 : radius, 12, 12]} />
        <meshBasicMaterial color={active || selected ? '#f2ffc7' : '#d4ef8a'} />
      </mesh>
      {(selected || active) && (
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[radius * 2.3, radius * 2.45, 32]} />
          <meshBasicMaterial color="#d4ef8a" transparent opacity={0.5} side={THREE.DoubleSide} />
        </mesh>
      )}
    </group>
  );
}

class SceneBoundary extends Component<
  { fallback: ReactNode; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function FlatMap({ data, ...props }: Props & { data: Geometry }) {
  const x = (lng: number) => (lng - 54.5) * 38,
    y = (lat: number) => (46 - lat) * 43;
  return (
    <svg
      className="flat-map"
      viewBox="0 0 760 420"
      aria-label={
        props.lang === 'ru' ? 'Карта регионов Узбекистана' : 'O‘zbekiston hududlari xaritasi'
      }
    >
      <defs>
        <linearGradient id="country-fill" x2="0.8" y2="1">
          <stop stopColor="#81986c" />
          <stop offset="1" stopColor="#304332" />
        </linearGradient>
      </defs>
      {data.features.map((feature) => {
        const path = feature.geometry.coordinates
          .map((polygon) =>
            polygon
              .map(
                (points) =>
                  points
                    .map(([lng, lat], i) => `${i === 0 ? 'M' : 'L'}${x(lng)},${y(lat)}`)
                    .join(' ') + ' Z',
              )
              .join(' '),
          )
          .join(' ');
        return (
          <path
            key={feature.properties.id}
            d={path}
            fill={props.selected === feature.properties.id ? '#a9c47f' : 'url(#country-fill)'}
            fillRule="evenodd"
            stroke="#b9d58f"
            strokeOpacity=".55"
            strokeWidth=".7"
            onClick={() => props.onSelect(feature.properties.id)}
            style={{ cursor: 'pointer' }}
          />
        );
      })}
      {props.routes.map((route, i) => {
        const a = props.regions.find((r) => r.id === route.origin),
          b = props.regions.find((r) => r.id === route.destination);
        return a && b ? (
          <path
            key={i}
            d={`M${x(a.lng)} ${y(a.lat)} Q${(x(a.lng) + x(b.lng)) / 2} ${Math.min(y(a.lat), y(b.lat)) - 35} ${x(b.lng)} ${y(b.lat)}`}
            fill="none"
            stroke="#d4ef8a"
            opacity=".25"
          />
        ) : null;
      })}
      {props.regions.map((r) => (
        <g
          key={r.id}
          role="button"
          tabIndex={0}
          aria-label={r[props.lang]}
          onClick={() => props.onSelect(r.id)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              props.onSelect(r.id);
            }
          }}
          style={{ cursor: 'pointer' }}
        >
          <circle cx={x(r.lng)} cy={y(r.lat)} r={props.selected === r.id ? 9 : 5} fill="#d4ef8a" />
          <circle
            cx={x(r.lng)}
            cy={y(r.lat)}
            r="13"
            fill="transparent"
            stroke="#d4ef8a"
            opacity=".3"
          />
          <title>{r[props.lang]}</title>
        </g>
      ))}
    </svg>
  );
}

export default function MapScene(props: Props) {
  const [data, setData] = useState<Geometry | null>(null);
  const [hover, setHover] = useState('');
  const [loadError, setLoadError] = useState(false);
  const [visible, setVisible] = useState(true);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), {
      rootMargin: '80px',
    });
    observer.observe(container.current);
    return () => observer.disconnect();
  }, [data, props.flat]);
  useEffect(() => {
    let alive = true;
    fetch('/uzbekistan-regions.geojson')
      .then((r) => {
        if (!r.ok) throw new Error('geometry');
        return r.json();
      })
      .then((d) => {
        if (alive) setData(d);
      })
      .catch(() => {
        if (alive) setLoadError(true);
      });
    return () => {
      alive = false;
    };
  }, []);
  const max = Math.max(1, ...props.stats.map((r) => Number(r.amount_uzs)));
  const activeRegion = props.regions.find((r) => r.id === (hover || props.selected));
  const activeStat = props.stats.find((r) => r.id === (hover || props.selected));
  if (!data)
    return (
      <div className="map-loading">
        {loadError
          ? props.lang === 'ru'
            ? 'Карта недоступна. Выберите регион в фильтре.'
            : 'Xarita mavjud emas. Hududni filtrdan tanlang.'
          : props.lang === 'ru'
            ? 'СОБИРАЕМ КАРТУ РЫНКА'
            : 'BOZOR XARITASI YUKLANMOQDA'}
        <span />
      </div>
    );
  const fallback = <FlatMap {...props} data={data} />;
  if (props.flat) return fallback;
  return (
    <>
      <div ref={container} className="map-canvas-container">
        <SceneBoundary fallback={fallback}>
          <Canvas
            frameloop={visible && !props.reduced ? 'always' : 'demand'}
            orthographic
            camera={{ position: [0, 27, 25], zoom: 16, near: 0.1, far: 200 }}
            dpr={[1, 1.5]}
            gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
            fallback={fallback}
            style={{ touchAction: 'pan-y' }}
          >
            <ambientLight intensity={1.2} />
            <directionalLight position={[-15, 24, -12]} intensity={3} color="#eeffd4" />
            <directionalLight position={[10, 10, 14]} intensity={1.2} color="#92aa86" />
            {data.features.map((feature) => (
              <RegionShape
                key={feature.properties.id}
                feature={feature}
                active={hover === feature.properties.id}
                selected={props.selected === feature.properties.id}
                weight={
                  Number(props.stats.find((s) => s.id === feature.properties.id)?.amount_uzs || 0) /
                  max
                }
                onHover={setHover}
                onSelect={props.onSelect}
              />
            ))}
            <GroundGrid />
            {props.routes.slice(0, 10).map((route, i) => {
              const a = props.regions.find((r) => r.id === route.origin),
                b = props.regions.find((r) => r.id === route.destination);
              return a && b ? (
                <Flow
                  key={`${route.origin}-${route.destination}`}
                  origin={a}
                  destination={b}
                  index={i}
                  reduced={props.reduced}
                />
              ) : null;
            })}
            {props.regions.map((r) => (
              <Node
                key={r.id}
                region={r}
                active={hover === r.id}
                selected={props.selected === r.id}
                weight={Number(props.stats.find((s) => s.id === r.id)?.amount_uzs || 0) / max}
                onHover={setHover}
                onSelect={props.onSelect}
              />
            ))}
            <Controls />
          </Canvas>
        </SceneBoundary>
      </div>
      {activeRegion && (
        <div className="map-tooltip">
          <span className="status-dot" />
          <span>{activeRegion[props.lang]}</span>
          <strong>
            {(activeStat?.deals || 0).toLocaleString('ru-RU')}{' '}
            {props.lang === 'ru' ? 'сделок' : 'bitim'}
          </strong>
        </div>
      )}
    </>
  );
}
