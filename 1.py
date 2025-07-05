import libtorrent as lt
import time
import os

save_path = os.path.abspath("downloads")
magnet_uri = "magnet:?xt=urn:btih:3e11d37465e520bade2144ae7e71d21f2757518d&dn=HEYZO-3626"

ses = lt.session()
params = {
    'save_path': save_path,
    'storage_mode': lt.storage_mode_t.storage_mode_sparse,
}
handle = lt.add_magnet_uri(ses, magnet_uri, params)

print("⏳ 正在获取种子信息...")
while not handle.has_metadata():
    time.sleep(1)

print("🚀 开始下载...")
while not handle.status().is_seeding:
    s = handle.status()
    print(f"📦 {s.name}: {s.progress * 100:.2f}% "
          f"(↓ {s.download_rate / 1000:.2f} KB/s, ↑ {s.upload_rate / 1000:.2f} KB/s, Peer: {s.num_peers})")
    time.sleep(5)

print("✅ 下载完成！文件保存在:", save_path)