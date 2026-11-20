/** 把浏览器录音的 MIME 类型映射成上传文件后缀，避免 WebM/MP4 被当成 WAV。 */
export function audioExtension(mime: string): string {
  const type = (mime || '').split(';')[0].trim().toLowerCase();
  if (type.includes('webm')) return 'webm';
  if (type.includes('ogg')) return 'ogg';
  if (type.includes('mp4')) return 'm4a';
  if (type.includes('mpeg')) return 'mp3';
  if (type.includes('wav')) return 'wav';
  if (type.includes('aac')) return 'aac';
  if (type.includes('flac')) return 'flac';
  if (type.includes('opus')) return 'opus';
  return 'webm';
}
