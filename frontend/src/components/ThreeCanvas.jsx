import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

const SECTORS = [
  { name: 'Agro', color: 0x00f5a0, pos: [3.2, 1.2, -1.5] },
  { name: 'Metallurgy', color: 0x00f2fe, pos: [-3.0, -1.8, 1.2] },
  { name: 'Energy', color: 0xffaa00, pos: [2.5, -2.2, 2.0] },
  { name: 'Food', color: 0x7f00ff, pos: [-2.8, 2.0, -1.8] },
  { name: 'Construction', color: 0x00c6ff, pos: [0.0, 3.5, 1.5] },
  { name: 'Chemistry', color: 0xff007f, pos: [1.8, -1.0, -3.2] },
];

export default function ThreeCanvas({ pulseTrigger }) {
  const mountRef = useRef(null);
  const pulseRef = useRef(null);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    // Scene, Camera, Renderer
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x06080d, 0.04);

    const camera = new THREE.PerspectiveCamera(
      55,
      container.clientWidth / container.clientHeight,
      0.1,
      1000
    );
    camera.position.set(0, 0, 8.5);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    container.appendChild(renderer.domElement);

    // Group for mouse parallax rotation
    const rootGroup = new THREE.Group();
    scene.add(rootGroup);

    // 1. Particle Galaxy (500k represented by 2500 glowing points)
    const particleCount = 2800;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);

    const colorPalette = [
      new THREE.Color(0x00f2fe),
      new THREE.Color(0x4facfe),
      new THREE.Color(0x00f5a0),
      new THREE.Color(0x7f00ff),
      new THREE.Color(0x38ef7d),
      new THREE.Color(0xffb300)
    ];

    for (let i = 0; i < particleCount; i++) {
      // Golden spiral sphere distribution
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 3.6 + (Math.random() - 0.5) * 1.8;

      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.sin(phi) * Math.sin(theta);
      const z = r * Math.cos(phi);

      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      const c = colorPalette[Math.floor(Math.random() * colorPalette.length)];
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    // Particle texture
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext('2d');
    const grad = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.3, 'rgba(0,242,254,0.8)');
    grad.addColorStop(0.7, 'rgba(0,242,254,0.15)');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 32, 32);
    const particleTexture = new THREE.CanvasTexture(canvas);

    const particleMaterial = new THREE.PointsMaterial({
      size: 0.12,
      map: particleTexture,
      transparent: true,
      vertexColors: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    const particles = new THREE.Points(geometry, particleMaterial);
    rootGroup.add(particles);

    // 2. Orbital Cyber Rings
    const ringGeo1 = new THREE.TorusGeometry(4.4, 0.015, 16, 120);
    const ringMat1 = new THREE.MeshBasicMaterial({
      color: 0x00f2fe,
      transparent: true,
      opacity: 0.35,
      blending: THREE.AdditiveBlending
    });
    const ring1 = new THREE.Mesh(ringGeo1, ringMat1);
    ring1.rotation.x = Math.PI / 3;
    ring1.rotation.y = Math.PI / 6;
    rootGroup.add(ring1);

    const ringGeo2 = new THREE.TorusGeometry(3.9, 0.012, 16, 120);
    const ringMat2 = new THREE.MeshBasicMaterial({
      color: 0x7f00ff,
      transparent: true,
      opacity: 0.25,
      blending: THREE.AdditiveBlending
    });
    const ring2 = new THREE.Mesh(ringGeo2, ringMat2);
    ring2.rotation.x = -Math.PI / 4;
    ring2.rotation.z = Math.PI / 5;
    rootGroup.add(ring2);

    // 3. Sector Hub Nodes
    const nodeMeshes = [];
    SECTORS.forEach(sec => {
      const nodeGeo = new THREE.SphereGeometry(0.18, 24, 24);
      const nodeMat = new THREE.MeshBasicMaterial({
        color: sec.color,
        wireframe: true
      });
      const node = new THREE.Mesh(nodeGeo, nodeMat);
      node.position.set(...sec.pos);

      // Inner glowing core
      const coreGeo = new THREE.SphereGeometry(0.1, 16, 16);
      const coreMat = new THREE.MeshBasicMaterial({
        color: 0xffffff
      });
      const core = new THREE.Mesh(coreGeo, coreMat);
      node.add(core);

      rootGroup.add(node);
      nodeMeshes.push(node);
    });

    // 4. Shockwave Pulse Mesh for AI Queries
    const shockwaveGeo = new THREE.SphereGeometry(0.1, 32, 32);
    const shockwaveMat = new THREE.MeshBasicMaterial({
      color: 0x00f2fe,
      transparent: true,
      opacity: 0,
      wireframe: true,
      blending: THREE.AdditiveBlending
    });
    const shockwave = new THREE.Mesh(shockwaveGeo, shockwaveMat);
    rootGroup.add(shockwave);

    pulseRef.current = () => {
      shockwave.scale.set(0.1, 0.1, 0.1);
      shockwaveMat.opacity = 0.85;
      shockwaveMat.color.setHex(0x00f2fe);
    };

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0x00f2fe, 3, 20);
    pointLight.position.set(0, 0, 4);
    scene.add(pointLight);

    // Mouse Parallax Interaction
    let targetRotX = 0;
    let targetRotY = 0;
    let currentRotX = 0;
    let currentRotY = 0;

    const handleMouseMove = (e) => {
      const rect = container.getBoundingClientRect();
      const normX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const normY = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      targetRotY = normX * 0.45;
      targetRotX = -normY * 0.35;
    };

    window.addEventListener('mousemove', handleMouseMove);

    // Animation Loop
    let animId;
    let clock = new THREE.Clock();

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const time = clock.getElapsedTime();

      // Smooth inertia parallax
      currentRotX += (targetRotX - currentRotX) * 0.04;
      currentRotY += (targetRotY - currentRotY) * 0.04;

      rootGroup.rotation.x = currentRotX;
      rootGroup.rotation.y = currentRotY + time * 0.05;

      // Rotate rings opposite
      ring1.rotation.z += 0.003;
      ring2.rotation.z -= 0.002;

      // Pulse sector nodes
      nodeMeshes.forEach((node, idx) => {
        const s = 1 + Math.sin(time * 3 + idx) * 0.15;
        node.scale.set(s, s, s);
      });

      // Handle query shockwave expansion
      if (shockwaveMat.opacity > 0.01) {
        shockwave.scale.addScalar(delta * 14.0);
        shockwaveMat.opacity -= delta * 0.9;
      }

      renderer.render(scene, camera);
    };
    animate();

    // Resize Handler
    const handleResize = () => {
      if (!container) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animId);
      if (container && renderer.domElement) {
        container.removeChild(renderer.domElement);
      }
      geometry.dispose();
      particleMaterial.dispose();
      particleTexture.dispose();
      ringGeo1.dispose();
      ringMat1.dispose();
      ringGeo2.dispose();
      ringMat2.dispose();
      shockwaveGeo.dispose();
      shockwaveMat.dispose();
      renderer.dispose();
    };
  }, []);

  // Trigger pulse whenever prop changes
  useEffect(() => {
    if (pulseTrigger && pulseRef.current) {
      pulseRef.current();
    }
  }, [pulseTrigger]);

  return (
    <div 
      ref={mountRef} 
      className="three-canvas-container"
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 0
      }}
    />
  );
}
