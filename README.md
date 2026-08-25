# PDF Translate

Dịch PDF sang tiếng Việt (hoặc ngôn ngữ hệ Latin khác) mà **giữ nguyên bố cục**: công thức toán, bảng, hình, mục lục, danh mục tài liệu tham khảo đều ở đúng chỗ cũ.

Không phải trích text ra rồi dịch thô. Công cụ dò bố cục từng trang bằng model layout, tách riêng vùng công thức và code để không đụng vào, dịch phần văn xuôi, rồi dựng lại PDF mới với chữ đã dịch đặt vào đúng khung cũ.

## Hai cách dùng

| | Dành cho ai | Cần gì |
| --- | --- | --- |
| **App desktop** | Ai cũng dùng được | Tải file, chạy, kéo thả PDF vào |
| **Claude Code skill** | Người đang dùng Claude Code | Thêm repo này vào skills |

## Tại sao dùng Google Translate mà không để AI dịch?

Câu hỏi hợp lý, và câu trả lời là: **cả hai đều có.**

**Google mode (mặc định)** — miễn phí, không cần API key, không tốn token, và quan trọng nhất: **chạy được mà không cần AI nào cả**. Đây chính là thứ khiến bản app desktop tồn tại được. Một file `.exe` không có agent để gọi, không có subscription, không có API key của bạn trong đó — nên nó phải dùng một backend dịch tự chạy được. Ngoài ra một cuốn sách 300 trang là vài nghìn đoạn văn; cho hết qua LLM là tốn tiền thật và chờ lâu thật.

**Handoff mode (nâng cao)** — dành cho người dùng Claude Code. Engine trích toàn bộ đoạn văn ra file, **chính agent trong khung chat dịch**, rồi engine dựng lại PDF. Thuật ngữ và ngữ cảnh tốt hơn hẳn Google, không gửi gì lên Google, và không cần API key vì nó dùng luôn phiên chat bạn đang có. Đổi lại: tốn token và chậm hơn.

Nói ngắn: **Google là mặc định rẻ, LLM là chế độ chất lượng, bạn chọn.** Bản `.exe` chỉ có Google mode — không phải vì lười, mà vì exe không có agent để gọi.

Chênh lệch chất lượng là thật. Trên một đoạn về truyền nhiệt, cùng từ *conduction*:

| | Kết quả |
| --- | --- |
| Google | "Sự **dẫn điện** xảy ra khi hai vật tiếp xúc trực tiếp" |
| Handoff | "**Dẫn nhiệt** xảy ra khi hai vật thể tiếp xúc trực tiếp với nhau" |

Google dịch *conduction* thành dẫn điện trong một văn bản về nhiệt. Đây đúng là loại lỗi mà mode LLM sinh ra để tránh.

## App desktop

Tải bản build mới nhất ở tab **Releases**, giải nén, chạy `PDFTranslate.exe`. Không cần cài Python, không cần mạng cho lần chạy đầu (model nhận diện bố cục và font đã đóng gói sẵn). Bản nén ~198 MB, giải nén ra ~382 MB.

Ba cách đưa file vào: kéo thả vào cửa sổ app, bấm nút *Chọn file* / *Chọn thư mục*, hoặc thả thẳng lên icon `PDFTranslate.exe`. Chọn ngôn ngữ đích rồi bấm **Dịch**. App xử lý lần lượt từng file và ghi kết quả vào thư mục `translated` bên cạnh file nguồn; một file lỗi không làm dừng cả loạt.

Hiện chỉ có bản Windows. Bản macOS chưa có vì PyInstaller không cross-compile được — phải build trên máy Mac thật.

## Claude Code skill

Clone repo vào thư mục skills của bạn, rồi:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Dùng trong chat:

> Use $pdf-translate to translate this PDF into Vietnamese.

Hoặc gọi thẳng runner:

```powershell
# Google mode
.venv\Scripts\python.exe scripts\translate_pdf.py INPUT.pdf --output-dir OUT

# Handoff mode: trích đoạn văn ra cho agent dịch
.venv\Scripts\python.exe scripts\translate_pdf.py INPUT.pdf --engine handoff --emit-segments segments.jsonl
# ...agent dịch segments.jsonl thành translations.jsonl...
.venv\Scripts\python.exe scripts\translate_pdf.py INPUT.pdf --engine handoff --segments translations.jsonl --output-dir OUT
```

Chi tiết quy trình handoff nằm trong [SKILL.md](SKILL.md).

## Ngôn ngữ hỗ trợ

Mặc định `vi`. Đổi bằng `--target-language`.

Hỗ trợ mọi ngôn ngữ **hệ chữ Latin**: `af ca cs cy da de en es et eu fi fr ga gl hr hu id is it lt lv ms mt nl no pl pt ro sk sl sq sv sw tl tr vi`

**Không** hỗ trợ Trung/Nhật/Hàn, Ả-Rập, Do Thái, Thái, Devanagari. Font đi kèm không có glyph cho các chữ đó, và bộ dựng chữ viết trái-sang-phải không xử lý được chữ nối hay dấu chồng. Truyền vào sẽ báo lỗi rõ ràng chứ không cho ra file đầy ô vuông.

## Hạn chế đã biết

- **Không có OCR.** PDF scan (chỉ có ảnh, không có text) sẽ không dịch được. Cần OCR trước.
- Chữ nằm trong vùng được nhận là bảng hoặc hình đôi khi bị giữ nguyên tiếng gốc. Kiểm tra lại output.
- Đoạn dài quá 5000 ký tự bị Google cắt bớt (hiếm, vì mỗi đoạn thường là một paragraph).
- Trang mục lục, index, danh mục ký hiệu và tài liệu tham khảo được **cố ý giữ nguyên bố cục**, không reflow — xem [references/preservation-rules.md](references/preservation-rules.md).

## Giấy phép

**AGPL-3.0.** Repo này là bản fork rút gọn của [PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate) 1.9.11 và [BabelDOC](https://github.com/funstory-ai/BabelDOC) — xem [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

AGPL đi theo cả bản binary: nếu bạn phát hành lại app hoặc chạy nó như một dịch vụ qua mạng, bạn phải cung cấp source tương ứng, và toàn bộ phần bạn thêm vào cũng ở lại AGPL. Không relicense sang MIT được.
