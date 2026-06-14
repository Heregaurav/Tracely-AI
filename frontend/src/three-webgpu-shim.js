// Minimal shim for 'three/webgpu' to satisfy imports when WebGPU isn't shipped
export class WebGPURenderer {
  constructor() {
    // Feature not available in this environment; keep as a no-op placeholder.
    // Code that depends on WebGPU should detect feature support and fallback.
    this.__unsupported = true
  }
  // stub methods that consumers may call
  setSize() {}
  setAnimationLoop() {}
  render() {}
}

export default { WebGPURenderer }
