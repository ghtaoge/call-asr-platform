export function encodeAudioFrame(
  sequence: number,
  capturedAtMs: bigint,
  pcm: Int16Array
): ArrayBuffer {
  const buffer = new ArrayBuffer(16 + pcm.byteLength);
  const view = new DataView(buffer);
  view.setUint8(0, 1);
  view.setUint8(1, 0);
  view.setUint16(2, 0, false);
  view.setUint32(4, sequence, false);
  view.setBigUint64(8, capturedAtMs, false);
  for (let index = 0; index < pcm.length; index += 1) {
    view.setInt16(16 + index * 2, pcm[index], true);
  }
  return buffer;
}
