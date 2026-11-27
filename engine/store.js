// Ronic Reader (iPad/iPhone): biblioteca no próprio aparelho (IndexedDB).
const DB = "ronic-reader", VER = 1;
let dbp = null;
function db() {
  if (!dbp) dbp = new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, VER);
    r.onupgradeneeded = () => {
      const d = r.result;
      d.createObjectStore("books", { keyPath: "id" });   // metadados + posição
      d.createObjectStore("files");                       // id -> bytes do PDF/EPUB
      d.createObjectStore("covers");                      // id -> imagem
      d.createObjectStore("kv");                          // preferências, ajustes
    };
    r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error);
  });
  return dbp;
}
async function tx(store, mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction(store, mode); const s = t.objectStore(store);
    let out; Promise.resolve(fn(s)).then((v) => { out = v; });
    t.oncomplete = () => resolve(out); t.onerror = () => reject(t.error);
  });
}
const req = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

export const get = (store, key) => tx(store, "readonly", (s) => req(s.get(key)));
export const put = (store, value, key) => tx(store, "readwrite", (s) => req(key === undefined ? s.put(value) : s.put(value, key)));
export const del = (store, key) => tx(store, "readwrite", (s) => req(s.delete(key)));
export const all = (store) => tx(store, "readonly", (s) => req(s.getAll()));

export async function fileId(bytes) {
  const h = await crypto.subtle.digest("SHA-1", bytes);
  return [...new Uint8Array(h)].slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
}
// pede ao Safari para não apagar a biblioteca quando faltar espaço
export async function persist() { try { await navigator.storage?.persist?.(); } catch (e) { /* opcional */ } }
