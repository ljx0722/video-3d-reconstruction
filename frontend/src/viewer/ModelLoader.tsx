import { useEffect, useLayoutEffect, useMemo } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { createCircleTexture, createGaussianTexture, createPresentationMaterial, getPointMaterialProfile, srgbToLinear } from './rendering';

interface ModelBounds {
  center: THREE.Vector3;
  radius: number;
  box: THREE.Box3;
}

interface Props {
  url: string;
  pointSize: number;
  opacity?: number;
  onPointsReady?: (mesh: THREE.Points, count: number) => void;
  onMeshReady?: (mesh: THREE.Group) => void;
  onCameraPositions?: (positions: Float32Array) => void;
  onBoundsReady?: (bounds: ModelBounds) => void;
  editedPointData?: { pos: Float32Array; col: Float32Array } | null;
  clipPlanes?: THREE.Plane[];
  viewMode?: 'points' | 'gaussian' | 'mesh' | 'wireframe';
  edgeThreshold?: number;
  edgeColor?: string;
  edgeOpacity?: number;
  colorsAreLinear?: boolean;
  gaussianRadius?: number;
  gaussianOpacity?: number;
  gaussianFalloff?: number;
  gaussianEdgeCutoff?: number;
  gaussianBlend?: 'normal' | 'additive';
  gaussianDepthWrite?: boolean;
  pointShape?: 'square' | 'circle';
  pointDepthTest?: boolean;
  surfaceRoughness?: number;
  surfaceMetalness?: number;
  surfaceColorBrightness?: number;
  surfaceFlatShading?: boolean;
  surfaceDoubleSide?: boolean;
}

interface ExtractedMesh {
  geometry: THREE.BufferGeometry;
  sourceMaterials: readonly THREE.Material[];
}

interface Extraction {
  pointGeometry: THREE.BufferGeometry | null;
  meshes: readonly ExtractedMesh[];
  cameraPositions: Float32Array;
}

const POINT_BUDGET = 2_000_000;
const DEFAULT_EDGE_COLOR = new THREE.Color('#6f89a3');
const SRGB_TO_LINEAR_LUT = Float32Array.from({ length: 256 }, (_, index) => srgbToLinear(index / 255));

function artifactColorToLinear(value: number, colorsAreLinear: boolean): number {
  if (colorsAreLinear) return Math.max(0, Math.min(1, value));
  return SRGB_TO_LINEAR_LUT[Math.min(255, Math.max(0, Math.round(value * 255)))];
}

function correctVertexColors(geometry: THREE.BufferGeometry, colorsAreLinear: boolean): void {
  const color = geometry.getAttribute('color');
  if (!color || color.itemSize < 3) return;

  const corrected = new Float32Array(color.count * color.itemSize);
  for (let index = 0; index < color.count; index += 1) {
    const offset = index * color.itemSize;
    corrected[offset] = artifactColorToLinear(color.getX(index), colorsAreLinear);
    corrected[offset + 1] = artifactColorToLinear(color.getY(index), colorsAreLinear);
    corrected[offset + 2] = artifactColorToLinear(color.getZ(index), colorsAreLinear);
    if (color.itemSize > 3) corrected[offset + 3] = color.getW(index);
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(corrected, color.itemSize));
}

function createMeshMaterial(
  source: THREE.Material | undefined,
  hasVertexColors: boolean,
  clipPlanes: THREE.Plane[] | undefined,
  polygonOffset: boolean,
  surfaceRoughness: number,
  surfaceMetalness: number,
  surfaceColorBrightness: number,
  surfaceFlatShading: boolean,
  surfaceDoubleSide: boolean,
): THREE.MeshStandardMaterial {
  const sourceMap = source instanceof THREE.MeshStandardMaterial && source.map ? source.map.clone() : null;
  const material = createPresentationMaterial(hasVertexColors, sourceMap, {
    roughness: surfaceRoughness,
    metalness: surfaceMetalness,
    colorBrightness: surfaceColorBrightness,
    flatShading: surfaceFlatShading,
    doubleSide: surfaceDoubleSide,
  });
  if (sourceMap) material.userData.ownedMap = sourceMap;
  material.clippingPlanes = clipPlanes ?? [];
  material.clipShadows = true;
  material.polygonOffset = polygonOffset;
  material.polygonOffsetFactor = polygonOffset ? 1 : 0;
  material.polygonOffsetUnits = polygonOffset ? 1 : 0;
  return material;
}

export default function ModelLoader({
  url,
  pointSize,
  opacity = 1,
  onPointsReady,
  onMeshReady,
  onCameraPositions,
  onBoundsReady,
  editedPointData,
  clipPlanes,
  viewMode = 'points',
  edgeThreshold = 30,
  edgeColor = '#6f89a3',
  edgeOpacity = 0.72,
  colorsAreLinear = false,
  gaussianRadius = 4,
  gaussianOpacity = 0.75,
  gaussianFalloff = 2,
  gaussianEdgeCutoff = 0,
  gaussianBlend = 'normal',
  gaussianDepthWrite = false,
  pointShape = 'square',
  pointDepthTest = true,
  surfaceRoughness = 0.82,
  surfaceMetalness = 0,
  surfaceColorBrightness = 1,
  surfaceFlatShading = false,
  surfaceDoubleSide = true,
}: Props) {
  const { scene } = useGLTF(url);
  const splatTex = useMemo(
    () => createGaussianTexture(gaussianFalloff, gaussianEdgeCutoff),
    [gaussianEdgeCutoff, gaussianFalloff],
  );
  const circleTex = useMemo(() => createCircleTexture(), []);

  // Extraction is independent of presentation mode. Traverse a local hierarchy clone so
  // matrixWorld can be updated without mutating the cached useGLTF scene or its resources.
  const extraction = useMemo<Extraction>(() => {
    const pointPositions: number[] = [];
    const pointColors: number[] = [];
    const cameraPositions: number[] = [];
    const meshes: ExtractedMesh[] = [];
    const worldPosition = new THREE.Vector3();

    try {
      const extractionScene = scene.clone(true);
      extractionScene.updateMatrixWorld(true);
      extractionScene.traverse((child) => {
        const renderable = child as THREE.Object3D & {
          isMesh?: boolean;
          geometry?: THREE.BufferGeometry;
          material?: THREE.Material | THREE.Material[];
        };
        const geometry = renderable.geometry;
        if (!geometry?.getAttribute) return;

        const position = geometry.getAttribute('position');
        if (!position || position.count === 0) return;

        if (renderable.isMesh) {
          let clonedGeometry: THREE.BufferGeometry | null = null;
          try {
            // Cloning preserves either indexed or non-indexed topology. Baking matrixWorld
            // keeps every mode detached from the source object's mutable transforms.
            clonedGeometry = geometry.clone();
            clonedGeometry.applyMatrix4(child.matrixWorld);
            correctVertexColors(clonedGeometry, colorsAreLinear);
            if (!clonedGeometry.getAttribute('normal')) clonedGeometry.computeVertexNormals();
            clonedGeometry.computeBoundingBox();
            clonedGeometry.computeBoundingSphere();

            const sourceMaterials = Array.isArray(renderable.material)
              ? [...renderable.material]
              : renderable.material
                ? [renderable.material]
                : [];
            meshes.push({ geometry: clonedGeometry, sourceMaterials });
          } catch {
            clonedGeometry?.dispose();
          }
          return;
        }

        const color = geometry.getAttribute('color');
        if (position.count < 50) {
          let centerX = 0;
          let centerY = 0;
          let centerZ = 0;
          try {
            for (let index = 0; index < position.count; index += 1) {
              worldPosition.fromBufferAttribute(position, index).applyMatrix4(child.matrixWorld);
              centerX += worldPosition.x;
              centerY += worldPosition.y;
              centerZ += worldPosition.z;
            }
            cameraPositions.push(
              centerX / position.count,
              centerY / position.count,
              centerZ / position.count,
            );
          } catch {
            // Skip malformed camera geometry while retaining the rest of the artifact.
          }
          return;
        }

        const step = position.count > POINT_BUDGET
          ? Math.ceil(position.count / POINT_BUDGET)
          : 1;
        try {
          for (let index = 0; index < position.count; index += step) {
            worldPosition.fromBufferAttribute(position, index).applyMatrix4(child.matrixWorld);
            pointPositions.push(worldPosition.x, worldPosition.y, worldPosition.z);
            pointColors.push(
              color ? artifactColorToLinear(color.getX(index), colorsAreLinear) : 1,
              color ? artifactColorToLinear(color.getY(index), colorsAreLinear) : 1,
              color ? artifactColorToLinear(color.getZ(index), colorsAreLinear) : 1,
            );
          }
        } catch {
          // Skip malformed point geometry while retaining the rest of the artifact.
        }
      });
    } catch (error) {
      console.warn('ModelLoader: scene traversal failed, using extracted data available so far', error);
    }

    let pointGeometry: THREE.BufferGeometry | null = null;
    if (pointPositions.length > 0) {
      pointGeometry = new THREE.BufferGeometry();
      pointGeometry.setAttribute(
        'position',
        new THREE.BufferAttribute(new Float32Array(pointPositions), 3),
      );
      pointGeometry.setAttribute(
        'color',
        new THREE.BufferAttribute(new Float32Array(pointColors), 3),
      );
      pointGeometry.computeBoundingBox();
      pointGeometry.computeBoundingSphere();
    }

    return {
      pointGeometry,
      meshes,
      cameraPositions: new Float32Array(cameraPositions),
    };
  }, [colorsAreLinear, scene]);

  useEffect(() => () => {
    extraction.pointGeometry?.dispose();
    extraction.meshes.forEach(({ geometry }) => geometry.dispose());
  }, [extraction]);

  useEffect(() => () => splatTex?.dispose(), [splatTex]);
  useEffect(() => () => circleTex?.dispose(), [circleTex]);

  useEffect(() => {
    if (onCameraPositions && extraction.cameraPositions.length > 0) {
      onCameraPositions(extraction.cameraPositions.slice());
    }
  }, [extraction.cameraPositions, onCameraPositions]);

  const isPointMode = viewMode === 'points' || viewMode === 'gaussian';
  const pointProfile = getPointMaterialProfile(viewMode, pointSize, opacity, {
    gaussianRadius,
    gaussianOpacity,
    gaussianFalloff,
    gaussianEdgeCutoff,
    gaussianBlend,
    gaussianDepthWrite,
    pointShape,
    pointDepthTest,
  });

  const displayPointGeometry = useMemo(() => {
    if (!extraction.pointGeometry) return null;
    if (!editedPointData) return extraction.pointGeometry;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(editedPointData.pos, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(editedPointData.col, 3));
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    return geometry;
  }, [editedPointData, extraction.pointGeometry]);

  useEffect(() => () => {
    if (displayPointGeometry && displayPointGeometry !== extraction.pointGeometry) {
      displayPointGeometry.dispose();
    }
  }, [displayPointGeometry, extraction.pointGeometry]);

  // Preserve edited point data across point/soft-point mode switches.
  const points = useMemo(() => {
    if (!displayPointGeometry) return null;
    const material = new THREE.PointsMaterial({
      vertexColors: true,
      sizeAttenuation: true,
      transparent: true,
      depthTest: true,
      depthWrite: true,
      blending: THREE.NormalBlending,
    });
    const nextPoints = new THREE.Points(displayPointGeometry, material);
    return nextPoints;
  }, [displayPointGeometry]);

  useLayoutEffect(() => {
    if (!points) return;
    const material = points.material as THREE.PointsMaterial;
    material.size = pointProfile.size;
    material.opacity = pointProfile.opacity;
    material.transparent = true;
    material.depthTest = pointProfile.depthTest;
    material.depthWrite = pointProfile.depthWrite;
    material.blending = pointProfile.blending;
    material.alphaTest = pointProfile.alphaTest;
    material.map = pointProfile.useSoftTexture ? splatTex : pointProfile.pointShape === 'circle' ? circleTex : null;
    material.clippingPlanes = clipPlanes ?? [];
    material.needsUpdate = true;
  }, [circleTex, clipPlanes, pointDepthTest, pointProfile.alphaTest, pointProfile.blending, pointProfile.depthTest, pointProfile.depthWrite, pointProfile.opacity, pointProfile.pointShape, pointProfile.size, pointProfile.useSoftTexture, points, splatTex]);

  useEffect(() => () => {
    const material = points?.material;
    if (Array.isArray(material)) material.forEach((item) => item.dispose());
    else material?.dispose();
  }, [points]);

  const meshPresentation = useMemo(() => {
    const isMeshMode = viewMode === 'mesh' || viewMode === 'wireframe';
    if (!isMeshMode || extraction.meshes.length === 0) return null;

    const showEdges = viewMode === 'wireframe';
    const threshold = Number.isFinite(edgeThreshold) ? Math.max(0, edgeThreshold) : 30;
    const group = new THREE.Group();
    const ownedMaterials: THREE.Material[] = [];
    const ownedEdgeGeometries: THREE.EdgesGeometry[] = [];
    let edgeMaterial: THREE.LineBasicMaterial | null = null;

    if (showEdges) {
      edgeMaterial = new THREE.LineBasicMaterial({
        color: DEFAULT_EDGE_COLOR,
        transparent: true,
        opacity: 0.72,
        depthTest: true,
        depthWrite: false,
        blending: THREE.NormalBlending,
      });
      edgeMaterial.clippingPlanes = [];
      edgeMaterial.clipShadows = false;
      ownedMaterials.push(edgeMaterial);
    }

    extraction.meshes.forEach(({ geometry, sourceMaterials }) => {
      const materials = (sourceMaterials.length > 0 ? sourceMaterials : [undefined]).map((source) => {
        const material = createMeshMaterial(
          source,
          geometry.hasAttribute('color'),
          undefined,
          showEdges,
          surfaceRoughness,
          surfaceMetalness,
          surfaceColorBrightness,
          surfaceFlatShading,
          surfaceDoubleSide,
        );
        ownedMaterials.push(material);
        return material;
      });
      const mesh = new THREE.Mesh(geometry, materials.length === 1 ? materials[0] : materials);
      group.add(mesh);

      if (showEdges && edgeMaterial) {
        const edgeGeometry = new THREE.EdgesGeometry(geometry, threshold);
        const edges = new THREE.LineSegments(edgeGeometry, edgeMaterial);
        edges.renderOrder = 1;
        ownedEdgeGeometries.push(edgeGeometry);
        group.add(edges);
      }
    });

    return { group, ownedMaterials, ownedEdgeGeometries };
  }, [
    edgeThreshold,
    extraction.meshes,
    surfaceColorBrightness,
    surfaceDoubleSide,
    surfaceFlatShading,
    surfaceMetalness,
    surfaceRoughness,
    viewMode,
  ]);

  useLayoutEffect(() => {
    if (!meshPresentation) return;
    meshPresentation.ownedMaterials.forEach((material) => {
      material.clippingPlanes = clipPlanes ?? [];
      if (material instanceof THREE.LineBasicMaterial) {
        material.color.set(edgeColor);
        material.opacity = edgeOpacity;
      }
      material.needsUpdate = true;
    });
  }, [clipPlanes, edgeColor, edgeOpacity, meshPresentation]);

  useEffect(() => () => {
    meshPresentation?.ownedEdgeGeometries.forEach((geometry) => geometry.dispose());
    meshPresentation?.ownedMaterials.forEach((material) => {
      const ownedMap = material.userData.ownedMap as THREE.Texture | undefined;
      ownedMap?.dispose();
      material.dispose();
    });
  }, [meshPresentation]);

  const meshGroup = meshPresentation?.group ?? null;
  const activeArtifact = isPointMode ? points : meshGroup;

  useEffect(() => {
    if (isPointMode && points && onPointsReady) {
      const position = points.geometry.getAttribute('position');
      onPointsReady(points, position?.count ?? 0);
    }
  }, [isPointMode, onPointsReady, points]);

  useEffect(() => {
    if (meshGroup && onMeshReady) onMeshReady(meshGroup);
  }, [meshGroup, onMeshReady]);

  useEffect(() => {
    if (!activeArtifact || !onBoundsReady) return;
    const box = new THREE.Box3().setFromObject(activeArtifact);
    if (box.isEmpty()) return;

    const center = box.getCenter(new THREE.Vector3());
    const radius = center.distanceTo(box.max);
    onBoundsReady({ center, radius, box });
  }, [activeArtifact, onBoundsReady]);

  if (!activeArtifact) return null;
  return <primitive object={activeArtifact} />;
}
