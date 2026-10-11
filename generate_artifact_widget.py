import base64
import os

artifact_dir = "/Users/madhusudhan/.gemini/antigravity/brain/3ba0254c-16aa-4376-a768-aac0e29adb0d"
os.makedirs(artifact_dir, exist_ok=True)

pdf_path = "/Users/madhusudhan/Desktop/Work-Space/NammaMove_AI/Time_Management_Slides_AllInOne.pdf"
pptx_path = "/Users/madhusudhan/Desktop/Work-Space/NammaMove_AI/Time_Management_For_College_Students.pptx"

with open(pdf_path, "rb") as f:
    pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

with open(pptx_path, "rb") as f:
    pptx_b64 = base64.b64encode(f.read()).decode("utf-8")

widget_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] antialiased p-3 m-0">
  <div class="bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] rounded-2xl p-5 shadow-md max-w-xl mx-auto">
    <div class="flex items-center space-x-3 mb-3">
      <div class="w-10 h-10 rounded-xl bg-orange-500/10 flex items-center justify-center text-orange-600 text-xl font-bold">
        📄
      </div>
      <div>
        <h3 class="font-bold text-base leading-tight">Time Management for College Students</h3>
        <p class="text-xs text-[var(--muted-foreground)]">5 Presentation Slides (All-in-One High-Res PDF)</p>
      </div>
    </div>
    
    <p class="text-sm text-[var(--muted-foreground)] mb-4 leading-relaxed">
      Click the download buttons below to save the PDF and editable PowerPoint directly to your computer:
    </p>

    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <a id="dl-pdf" download="Time_Management_Slides_AllInOne.pdf"
         class="flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-[#FA6E38] hover:bg-[#E05D2B] text-white font-semibold text-sm transition-all shadow-sm cursor-pointer no-underline">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
        </svg>
        Download PDF (1.4 MB)
      </a>

      <a id="dl-pptx" download="Time_Management_For_College_Students.pptx"
         class="flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-[#0F2648] hover:bg-[#1A3A68] text-white font-semibold text-sm transition-all shadow-sm cursor-pointer no-underline">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"></path>
        </svg>
        Download PPTX (40 KB)
      </a>
    </div>

    <div class="mt-4 pt-3 border-t border-[var(--border)] flex items-center justify-between text-xs text-[var(--muted-foreground)]">
      <span>✓ 16:9 Widescreen Presentation</span>
      <span>5 Balanced Visual Slides</span>
    </div>
  </div>

  <script>
    const pdfBlob = b64toBlob('{pdf_b64}', 'application/pdf');
    const pptxBlob = b64toBlob('{pptx_b64}', 'application/vnd.openxmlformats-officedocument.presentationml.presentation');

    document.getElementById('dl-pdf').href = URL.createObjectURL(pdfBlob);
    document.getElementById('dl-pptx').href = URL.createObjectURL(pptxBlob);

    function b64toBlob(b64Data, contentType) {{
      const byteCharacters = atob(b64Data);
      const byteArrays = [];
      for (let offset = 0; offset < byteCharacters.length; offset += 512) {{
        const slice = byteCharacters.slice(offset, offset + 512);
        const byteNumbers = new Array(slice.length);
        for (let i = 0; i < slice.length; i++) {{
          byteNumbers[i] = slice.charCodeAt(i);
        }}
        const byteArray = new Uint8Array(byteNumbers);
        byteArrays.push(byteArray);
      }}
      return new Blob(byteArrays, {{type: contentType}});
    }}
  </script>
</body>
</html>
"""

target_file = os.path.join(artifact_dir, "download_presentation.html")
with open(target_file, "w", encoding="utf-8") as f:
    f.write(widget_html)

print("Artifact written to:", target_file)
