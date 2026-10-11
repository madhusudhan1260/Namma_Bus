import base64
import os

pdf_path = "/Users/madhusudhan/Desktop/Work-Space/NammaMove_AI/Time_Management_Slides_AllInOne.pdf"
pptx_path = "/Users/madhusudhan/Desktop/Work-Space/NammaMove_AI/Time_Management_For_College_Students.pptx"

with open(pdf_path, "rb") as f:
    pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

with open(pptx_path, "rb") as f:
    pptx_b64 = base64.b64encode(f.read()).decode("utf-8")

slide_imgs_b64 = []
for i in range(1, 6):
    img_p = f"/Users/madhusudhan/Desktop/Work-Space/NammaMove_AI/slide_img-{i}.png"
    with open(img_p, "rb") as f:
        slide_imgs_b64.append(base64.b64encode(f.read()).decode("utf-8"))

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Time Management Slides - Download & Viewer</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #FAF6EC;
            color: #18202C;
            margin: 0;
            padding: 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .header {{
            text-align: center;
            margin-bottom: 24px;
            max-width: 900px;
        }}
        h1 {{
            margin: 0 0 8px 0;
            font-size: 28px;
            color: #0F2648;
        }}
        p {{
            margin: 0 0 18px 0;
            color: #5A6E85;
            font-size: 15px;
        }}
        .download-bar {{
            display: flex;
            gap: 16px;
            margin-bottom: 30px;
            flex-wrap: wrap;
            justify-content: center;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 24px;
            border-radius: 10px;
            text-decoration: none;
            font-weight: 700;
            font-size: 15px;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
            cursor: pointer;
            border: none;
        }}
        .btn-pdf {{
            background-color: #FA6E38;
            color: #FFFFFF;
            box-shadow: 0 4px 12px rgba(250, 110, 56, 0.35);
        }}
        .btn-pptx {{
            background-color: #0F2648;
            color: #FFFFFF;
            box-shadow: 0 4px 12px rgba(15, 38, 72, 0.35);
        }}
        .btn:hover {{
            transform: translateY(-2px);
        }}
        .slides-container {{
            display: flex;
            flex-direction: column;
            gap: 24px;
            max-width: 1050px;
            width: 100%;
        }}
        .slide-card {{
            background: #FFFFFF;
            border-radius: 14px;
            box-shadow: 0 6px 20px rgba(0,0,0,0.06);
            overflow: hidden;
            border: 1px solid #E4DCCB;
        }}
        .slide-header {{
            padding: 10px 18px;
            background: #F2ECDE;
            font-weight: 700;
            font-size: 13px;
            color: #0F2648;
            display: flex;
            justify-content: space-between;
        }}
        .slide-card img {{
            width: 100%;
            height: auto;
            display: block;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>TIME MANAGEMENT FOR COLLEGE STUDENTS</h1>
        <p>5-Slide Visual Presentation • Click below to directly download the PDF or PPTX file to your device</p>
        
        <div class="download-bar">
            <a id="download-pdf" class="btn btn-pdf" download="Time_Management_Slides_AllInOne.pdf">
                ⬇ Download Combined PDF (1.4 MB)
            </a>
            <a id="download-pptx" class="btn btn-pptx" download="Time_Management_For_College_Students.pptx">
                📊 Download Editable PowerPoint (.pptx)
            </a>
        </div>
    </div>

    <div class="slides-container">
"""

for idx, b64 in enumerate(slide_imgs_b64, 1):
    html_content += f"""
        <div class="slide-card">
            <div class="slide-header">
                <span>SLIDE {idx} OF 5</span>
                <span>16:9 Widescreen</span>
            </div>
            <img src="data:image/png;base64,{b64}" alt="Slide {idx}">
        </div>
    """

html_content += f"""
    </div>

    <script>
        document.getElementById('download-pdf').href = 'data:application/pdf;base64,{pdf_b64}';
        document.getElementById('download-pptx').href = 'data:application/vnd.openxmlformats-officedocument.presentationml.presentation;base64,{pptx_b64}';
    </script>
</body>
</html>
"""

output_html = "/Users/madhusudhan/Desktop/Work-Space/NammaMove_AI/view_and_download_presentation.html"
with open(output_html, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Interactive download page created: {output_html}")
