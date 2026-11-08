/* Authenticated immutable media. IndexedDB persists bytes; object URLs avoid tab-switch downloads. */
let database,
  epoch = 0;
const memory = new Map();
const LIMIT = 160 * 1024 * 1024;
const DB_NAME = "case-studio-preview-media-v1";

function db() {
  if (!globalThis.indexedDB) return Promise.resolve(null);
  if (!database)
    database = new Promise((resolve) => {
      let blocked = false;
      const request = indexedDB.open(DB_NAME, 2);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains("images"))
          request.result.createObjectStore("images", { keyPath: "url" });
        else request.transaction.objectStore("images").clear(); // disposable v1 cache
        request.result.createObjectStore("metadata", { keyPath: "url" });
      };
      request.onblocked = () => { blocked = true; resolve(null); };
      request.onsuccess = () => {
        if (blocked) { request.result.close(); return; }
        request.result.onversionchange = () => { request.result.close(); database = null; };
        resolve(request.result);
      };
      request.onerror = () => resolve(null);
    });
  return database;
}

async function readBlob(url) {
  const connection = await db();
  if (!connection) return null;
  return new Promise((resolve) => {
    const request = connection
      .transaction("images")
      .objectStore("images")
      .get(url);
    request.onsuccess = () => resolve(request.result?.blob || null);
    request.onerror = () => resolve(null);
  });
}

async function persist(url, blob, generation) {
  const connection = await db();
  if (!connection || epoch !== generation || blob.size > LIMIT) return;
  await new Promise((resolve) => {
    const tx = connection.transaction(["images", "metadata"], "readwrite");
    const store = tx.objectStore("images");
    const metadata = tx.objectStore("metadata");
    store.put({ url, blob });
    metadata.put({ url, size: blob.size, used: Date.now() });
    const request = metadata.getAll();
    request.onsuccess = () => {
      const rows = request.result.sort((a, b) => a.used - b.used);
      let total = rows.reduce((n, row) => n + row.size, 0);
      for (const row of rows) {
        if (total <= LIMIT) break;
        if (row.url !== url) {
          store.delete(row.url);
          metadata.delete(row.url);
          total -= row.size;
        }
      }
    };
    tx.oncomplete = tx.onerror = tx.onabort = () => resolve();
  });
}

export function imageURL(url) {
  if (memory.has(url)) {
    const existing = memory.get(url);
    memory.delete(url);
    memory.set(url, existing);
    return existing.promise;
  }
  const generation = epoch,
    entry = {};
  memory.set(url, entry);
  entry.promise = (async () => {
    let blob = await readBlob(url);
    if (!blob) {
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (
        !response.ok ||
        !response.headers.get("Content-Type")?.startsWith("image/")
      )
        throw new Error("图片加载失败，请重新登录或重试");
      blob = await response.blob();
    }
    if (generation !== epoch) throw new Error("登录状态已改变");
    entry.objectURL = URL.createObjectURL(blob);
    entry.size = blob.size;
    // Decode once so switching orientation does not repeatedly decode a large JPEG.
    if (typeof Image !== "undefined") {
      entry.image = new Image();
      entry.image.src = entry.objectURL;
      await entry.image.decode();
    }
    if (generation !== epoch) {
      URL.revokeObjectURL(entry.objectURL);
      throw new Error("登录状态已改变");
    }
    // The image is ready; IndexedDB writes/eviction must not delay its display.
    void persist(url, blob, generation).catch(() => {});
    let bytes = [...memory.values()].reduce(
      (n, value) => n + (value.size || 0),
      0,
    );
    for (const [old, value] of memory) {
      if (memory.size <= 16 && bytes <= 80 * 1024 * 1024) break;
      if (old !== url && value.objectURL) {
        URL.revokeObjectURL(value.objectURL);
        bytes -= value.size;
        memory.delete(old);
      }
    }
    return entry.objectURL;
  })().catch((e) => {
    if (entry.objectURL) URL.revokeObjectURL(entry.objectURL);
    if (memory.get(url) === entry) memory.delete(url);
    throw e;
  });
  return entry.promise;
}

export async function clearMediaCache() {
  epoch++;
  for (const item of memory.values())
    if (item.objectURL) URL.revokeObjectURL(item.objectURL);
  memory.clear();
  const connection = await db();
  if (connection)
    await new Promise((resolve) => {
      const tx = connection.transaction(["images", "metadata"], "readwrite");
      tx.objectStore("images").clear();
      tx.objectStore("metadata").clear();
      tx.oncomplete = tx.onerror = tx.onabort = () => resolve();
    });
}
