// Draws a model with three.js. Imported only through `import()` by `ModelView`, so a page without a model never loads it.
// The GLB is metres and Y-up (glTF's convention); here it is turned and scaled to build123d's frame, millimetres and
// Z up, so what a person points at is where the script put it. Throws `NoWebGl` when the browser cannot draw.
import {
  AmbientLight, Box3, Color, DirectionalLight, EdgesGeometry, GridHelper, Group, HemisphereLight, LineBasicMaterial, LineSegments, Mesh,
  MeshStandardMaterial, OrthographicCamera, PerspectiveCamera, Scene, Sphere, Vector3, WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { NoWebGl } from './noWebGl';
import { distanceToFit, orthoHalfHeight, unit, VIEWS, type Vec3, type ViewPreset } from './views';

export interface Stage {
  /** The model's extent in millimetres, x y z. */
  size: Vec3;
  dispose(): void;
}

const FOV = 38;
const BACKGROUND = new Color('#08101a');
const PART = new Color('#8cc4ff');
const EDGE = new Color('#0c1622');

function rendererOn(canvas: HTMLCanvasElement): WebGLRenderer {
  try {
    const r = new WebGLRenderer({ canvas, antialias: true });
    r.setClearColor(BACKGROUND, 1);
    return r;
  } catch {
    throw new NoWebGl('this browser cannot draw WebGL');
  }
}

/** Frees the canvas's GL context now rather than when the page is collected: a look page may hold several models. */
function release(renderer: WebGLRenderer): void {
  renderer.dispose();
  renderer.forceContextLoss();
}

function parse(glb: ArrayBuffer): Promise<Group> {
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(glb, '', (g) => resolve(g.scene), reject);
  });
}

/** The parts in millimetres and Z up, shaded one way so a run's colours or metal do not change how it reads. */
async function modelFrom(glb: ArrayBuffer): Promise<Group> {
  const scene = await parse(glb);
  const edges = new LineBasicMaterial({ color: EDGE });
  scene.traverse((o) => {
    if (!(o instanceof Mesh)) return;
    o.material = new MeshStandardMaterial({ color: PART, roughness: 0.55, metalness: 0.05 });
    o.add(new LineSegments(new EdgesGeometry(o.geometry, 30), edges));
  });
  const model = new Group();
  model.add(scene);
  model.scale.setScalar(1000);
  model.rotation.x = Math.PI / 2;
  model.updateMatrixWorld(true);
  return model;
}

function litSceneOf(model: Group, bounds: Box3): Scene {
  const scene = new Scene();
  scene.add(model, new AmbientLight('#ffffff', 0.5), new HemisphereLight('#cfe6ff', '#1b2d44', 1.1));
  const sun = new DirectionalLight('#ffffff', 2.2);
  sun.position.set(1.2, -2, 3).multiplyScalar(bounds.getBoundingSphere(new Sphere()).radius);
  scene.add(sun);
  const grid = new GridHelper(Math.max(bounds.max.x - bounds.min.x, bounds.max.y - bounds.min.y) * 2.4, 12, '#2a4566', '#1b2d44');
  grid.rotation.x = Math.PI / 2;
  grid.position.set(0, 0, bounds.min.z);
  scene.add(grid);
  return scene;
}

function extentOf(bounds: Box3): Vec3 {
  const s = bounds.getSize(new Vector3());
  return [s.x, s.y, s.z];
}

/** The share of the screen's pixel ratio the view draws at while it is being dragged; software WebGL is bound by fill rate. */
const DRAG_DETAIL = 0.5;

function resizeTo(canvas: HTMLCanvasElement, renderer: WebGLRenderer, detail = 1): { w: number; h: number } {
  const w = Math.max(1, canvas.clientWidth);
  const h = Math.max(1, canvas.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2) * detail);
  renderer.setSize(w, h, false);
  return { w, h };
}

/** An orbitable view of the model, fitted to the canvas. Draws only when something changes. */
export async function openStage(canvas: HTMLCanvasElement, glb: ArrayBuffer): Promise<Stage> {
  const model = await modelFrom(glb);
  const renderer = rendererOn(canvas);
  const bounds = new Box3().setFromObject(model);
  const sphere = bounds.getBoundingSphere(new Sphere());
  const scene = litSceneOf(model, bounds);
  const camera = new PerspectiveCamera(FOV, 1, sphere.radius / 100, sphere.radius * 100);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, canvas);
  controls.target.copy(sphere.center);
  let frame = 0;
  let detail = 1;
  const draw = () => { frame = 0; renderer.render(scene, camera); };
  const later = () => { if (!frame) frame = requestAnimationFrame(draw); };
  const resize = () => {
    const { w, h } = resizeTo(canvas, renderer, detail);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    later();
  };
  const fit = () => {
    resize();
    const away = unit(VIEWS[0]!.toward);
    const d = distanceToFit(sphere.radius, FOV, camera.aspect) * 1.25;
    camera.position.copy(sphere.center).addScaledVector(new Vector3(...away), d);
    controls.update();
    later();
  };
  controls.addEventListener('change', later);
  const dragAt = (d: number) => () => { detail = d; resize(); };
  controls.addEventListener('start', dragAt(DRAG_DETAIL));
  controls.addEventListener('end', dragAt(1));
  fit();
  const watch = new ResizeObserver(() => { fit(); });
  watch.observe(canvas);
  draw();
  return {
    size: extentOf(bounds),
    dispose() {
      watch.disconnect();
      cancelAnimationFrame(frame);
      controls.dispose();
      release(renderer);
    },
  };
}

/** The four views of `VIEWS` in one canvas, two by two, each looking at the whole model from its side; drawn once. With
 * `only`, that one side fills the canvas instead. */
export async function drawSheet(canvas: HTMLCanvasElement, glb: ArrayBuffer, only: ViewPreset | null = null): Promise<Stage> {
  const model = await modelFrom(glb);
  const renderer = rendererOn(canvas);
  const bounds = new Box3().setFromObject(model);
  const sphere = bounds.getBoundingSphere(new Sphere());
  const scene = litSceneOf(model, bounds);
  const { w, h } = resizeTo(canvas, renderer);
  const cw = only ? w : Math.floor(w / 2);
  const ch = only ? h : Math.floor(h / 2);
  renderer.setScissorTest(true);
  (only ? [only] : VIEWS).forEach((view, i) => {
    const half = orthoHalfHeight(sphere.radius, cw / ch);
    const camera = new OrthographicCamera(-half * (cw / ch), half * (cw / ch), half, -half, sphere.radius / 100, sphere.radius * 100);
    camera.up.set(...view.up);
    camera.position.copy(sphere.center).addScaledVector(new Vector3(...unit(view.toward)), sphere.radius * 4);
    camera.lookAt(sphere.center);
    const x = (i % 2) * cw;
    const y = ch - Math.floor(i / 2) * ch;
    renderer.setViewport(x, y, cw, ch);
    renderer.setScissor(x, y, cw, ch);
    renderer.render(scene, camera);
  });
  return { size: extentOf(bounds), dispose: () => release(renderer) };
}
