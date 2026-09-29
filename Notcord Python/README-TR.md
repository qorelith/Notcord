# Notcord 🚀
> **Discord Mesaj ve Favori GIF Temizleyici / Discord Message & Favorite GIF Purger**  
> **Geliştirici / Author:** **Qorelith**

---

<p align="center">
  <img src="assets/logo.png" width="160" alt="Notcord Logo" />
</p>

## 🌟 Özellikler (Features)

- ⚡ **Turbo Hızlı Silme (~5-7 Mesaj/Saniye):** Persistent HTTP bağlantısı (Keep-Alive) ve `0.15s` (veya ayarlanabilir `0.05s - 3.50s`) gecikme ile saniyede 5+ mesaj silme kapasitesi.
- ➕ **ID ile Hedef Ekleme:** Arkadaş ekli olmadığınız kişilerin Kullanıcı ID'sini (User ID) veya herhangi bir Kanal ID'sini (Channel ID) yazarak doğrudan sohbeti açıp temizleme.
- 💬 **Kişiye veya Gruba Özel Temizleme:** Arkadaş (DM), Grup Sohbeti veya Sunucu kanalı seçerek sizin attığınız mesajları siler.
- ⚡ **Gelişmiş Mesaj Filtreleri:**
  - *Tüm Mesajlar:* Seçilen aralıktaki tüm mesajlarınızı siler.
  - *Sadece Fotoğraflar:* Yalnızca görsel/resim ekli mesajları siler.
  - *Sadece GIF'ler:* GIF formatındaki mesajları temizler.
  - *Sadece Normal Mesajlar:* Medya içermeyen yalnızca düz metin mesajlarını siler.
- ⏳ **Zaman Aralığı Seçenekleri:**
  - Son 1 Saat
  - Son 6 Saat
  - Son 24 Saat (1 Gün)
  - Son 7 Gün
  - Son 30 Gün
  - Özel Süre (Belirlediğiniz saat veya gün sayısı)
  - Tüm Zamanlar (Sınırsız)
- ⭐ **Favori GIF Temizleyici:** Hesabınızda favorilere eklenmiş tüm GIF'leri veya Belli zaman aralıklarından önce veya sonra (örnek: son 6 ayda / ilk 6 ayda) tek tıkla hesabınızdan siler.
- 🖥 **Canlı Etkinlik Konsolu:** Silinen mesajların ID'leri, içerik önizlemeleri ve Discord hız sınırı (429) durumları renkli terminalde anlık olarak görüntülenir.
- 🛑 **Güvenli Durdurma:** İstediğiniz an silme işlemini durdurabilirsiniz.
- 🌐 **Beş Dil Desteği:** Türkçe, İngilizce, İspanyolca, Portekizce, Rusça arasında tek tıkla dinamik geçiş.
- 🎨 **Discord Benzeri Modern Tasarım:** CustomTkinter ile hazırlanmış kırmızı, koyu gri, siyah ve beyaz renk şeması.

---

## 🛠 Kurulum ve Çalıştırma

## 📥 Kullanıcılar İçin (Kolay Yol)
Eğer sadece programı kullanmak istiyorsan:
1. Sağ taraftaki **Releases** sekmesine git.
2. En son sürümdeki `.exe` dosyasını indir.
3. Direkt çalıştır! (Ekstra Python veya kütüphane kurulumu **gerekmez**).

## 💻 Geliştiriciler İçin (Kaynak Kod)
Eğer kodu incelemek veya katkıda bulunmak istiyorsan:

Gerekli kütüphaneleri yükleyin:
```bash
pip install -r requirements.txt
```

Programı başlatın:
```bash
python notcord.py
```

---

## 🔒 Güvenlik Notu

Notcord, hesabınızın tokenını **yalnızca yerel olarak** doğrudan resmi Discord HTTPS API'si (`discord.com/api/v9`) ile iletişim kurmak için kullanır. Tokenınız asla üçüncü bir sunucuya iletilmez.

---
**Created by Qorelith**
