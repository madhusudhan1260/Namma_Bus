import sys
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

def create_presentation():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Clean Color Palette
    COLOR_BG = RGBColor(0xFA, 0xF6, 0xEC)          # Warm cream #FAF6EC
    COLOR_NAVY = RGBColor(0x0F, 0x26, 0x48)        # Dark navy #0F2648
    COLOR_TEXT_BLACK = RGBColor(0x18, 0x20, 0x2C)  # Deep readable dark
    COLOR_MUTED = RGBColor(0x5A, 0x6E, 0x85)       # Soft blue-grey
    COLOR_MUTED_LIGHT = RGBColor(0x8A, 0x9B, 0xAD) # Lighter slate
    COLOR_ORANGE = RGBColor(0xFA, 0x6E, 0x38)      # Warm vibrant orange #FA6E38
    COLOR_ORANGE_BG = RGBColor(0xFF, 0xF0, 0xE8)   # Orange tint card
    COLOR_BLUE = RGBColor(0x1D, 0x70, 0xB8)        # Clean rich blue
    COLOR_BLUE_BG = RGBColor(0xEA, 0xF3, 0xFB)     # Light blue card
    COLOR_GREEN = RGBColor(0x13, 0x88, 0x54)       # Clean success green
    COLOR_GREEN_BG = RGBColor(0xE8, 0xF7, 0xEE)    # Light green card
    COLOR_WHITE = RGBColor(0xFF, 0xFF, 0xFF)       # Pure white
    COLOR_RED = RGBColor(0xD9, 0x38, 0x3A)         # Warning red
    COLOR_RED_BG = RGBColor(0xFD, 0xEA, 0xEA)      # Light red card
    COLOR_BORDER = RGBColor(0xE4, 0xDC, 0xCB)      # Subtle warm outline
    COLOR_GOLD = RGBColor(0xFF, 0xCA, 0x6E)        # Warm gold highlight

    FONT_HEADING = "Arial"
    FONT_BODY = "Arial"

    def set_slide_background(slide):
        bg_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5))
        bg_shape.fill.solid()
        bg_shape.fill.fore_color.rgb = COLOR_BG
        bg_shape.line.fill.background()
        return bg_shape

    def add_card(slide, left, top, width, height, fill_color=COLOR_WHITE, border_color=COLOR_BORDER, border_width=1, shape_type=MSO_SHAPE.ROUNDED_RECTANGLE):
        card = slide.shapes.add_shape(shape_type, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = fill_color
        if border_color:
            card.line.color.rgb = border_color
            card.line.width = Pt(border_width)
        else:
            card.line.fill.background()
        return card

    def add_badge(slide, left, top, width, height, text, bg_color=COLOR_BLUE_BG, text_color=COLOR_BLUE, font_size=11, bold=True):
        badge = add_card(slide, left, top, width, height, fill_color=bg_color, border_color=None, shape_type=MSO_SHAPE.ROUNDED_RECTANGLE)
        tf = badge.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.text = text
        p.alignment = PP_ALIGN.CENTER
        p.font.name = FONT_HEADING
        p.font.size = Pt(font_size)
        p.font.bold = bold
        p.font.color.rgb = text_color
        return badge

    def add_header(slide, tag_text, title_text, subtitle_text=None, tag_bg=COLOR_BLUE_BG, tag_color=COLOR_BLUE):
        add_badge(slide, Inches(0.8), Inches(0.4), Inches(2.2), Inches(0.35), tag_text, bg_color=tag_bg, text_color=tag_color, font_size=11, bold=True)
        
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.78), Inches(11.733), Inches(0.65))
        tf = title_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = title_text
        p.font.name = FONT_HEADING
        p.font.size = Pt(28)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_BLACK

        if subtitle_text:
            sub_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.42), Inches(11.733), Inches(0.42))
            tf_sub = sub_box.text_frame
            tf_sub.word_wrap = True
            tf_sub.margin_left = tf_sub.margin_top = tf_sub.margin_right = tf_sub.margin_bottom = 0
            p_sub = tf_sub.paragraphs[0]
            p_sub.text = subtitle_text
            p_sub.font.name = FONT_BODY
            p_sub.font.size = Pt(15)
            p_sub.font.color.rgb = COLOR_MUTED

    # =========================================================================
    # SLIDE 1: INTRODUCTION (Balanced Layout: 6 Surrounding Cards Around Center)
    # =========================================================================
    slide1 = prs.slides.add_slide(blank_layout)
    set_slide_background(slide1)

    # Top Tag
    add_badge(slide1, Inches(0.8), Inches(0.45), Inches(2.8), Inches(0.36), "COLLEGE SUCCESS SERIES", bg_color=COLOR_BLUE_BG, text_color=COLOR_BLUE, font_size=11)

    # Title & Subtitle
    t_box = slide1.shapes.add_textbox(Inches(0.8), Inches(0.92), Inches(5.8), Inches(1.2))
    tf = t_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = "TIME MANAGEMENT"
    p.font.name = FONT_HEADING
    p.font.size = Pt(38)
    p.font.bold = True
    p.font.color.rgb = COLOR_TEXT_BLACK

    sub_box = slide1.shapes.add_textbox(Inches(0.8), Inches(2.05), Inches(5.8), Inches(0.65))
    tf_sub = sub_box.text_frame
    tf_sub.word_wrap = True
    tf_sub.margin_left = tf_sub.margin_top = tf_sub.margin_right = tf_sub.margin_bottom = 0
    p_sub = tf_sub.paragraphs[0]
    p_sub.text = "How to Plan Your Time AND Actually Use It"
    p_sub.font.name = FONT_HEADING
    p_sub.font.size = Pt(19)
    p_sub.font.bold = True
    p_sub.font.color.rgb = COLOR_BLUE

    # Supporting Line Badge
    s_banner = add_card(slide1, Inches(0.8), Inches(2.78), Inches(4.5), Inches(0.48), fill_color=COLOR_ORANGE_BG, border_color=COLOR_ORANGE, border_width=1)
    tf_sb = s_banner.text_frame
    tf_sb.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_sb = tf_sb.paragraphs[0]
    p_sb.text = "Plan less.  Do better.  Stress less."
    p_sb.alignment = PP_ALIGN.CENTER
    p_sb.font.name = FONT_HEADING
    p_sb.font.size = Pt(13)
    p_sb.font.bold = True
    p_sb.font.color.rgb = COLOR_ORANGE

    # Navy Hero Card: 24 Hours & Core Message
    navy_card = add_card(slide1, Inches(0.8), Inches(3.48), Inches(5.7), Inches(2.75), fill_color=COLOR_NAVY, border_color=None)
    
    # 24 Hours badge
    c24 = add_card(slide1, Inches(1.1), Inches(3.72), Inches(1.6), Inches(0.46), fill_color=COLOR_ORANGE, border_color=None)
    tf_c24 = c24.text_frame
    tf_c24.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_c24 = tf_c24.paragraphs[0]
    p_c24.text = "24 HOURS"
    p_c24.alignment = PP_ALIGN.CENTER
    p_c24.font.name = FONT_HEADING
    p_c24.font.size = Pt(13)
    p_c24.font.bold = True
    p_c24.font.color.rgb = COLOR_WHITE

    c24_sub = slide1.shapes.add_textbox(Inches(2.85), Inches(3.72), Inches(3.4), Inches(0.46))
    tf_c24s = c24_sub.text_frame
    tf_c24s.word_wrap = True
    tf_c24s.margin_left = tf_c24s.margin_top = tf_c24s.margin_right = tf_c24s.margin_bottom = 0
    p_c24s = tf_c24s.paragraphs[0]
    p_c24s.text = "Every student gets the exact same bank."
    p_c24s.font.name = FONT_BODY
    p_c24s.font.size = Pt(12)
    p_c24s.font.color.rgb = RGBColor(0xBD, 0xCD, 0xDE)

    # Core message in navy card
    msg_box = slide1.shapes.add_textbox(Inches(1.1), Inches(4.45), Inches(5.1), Inches(1.5))
    tf_msg = msg_box.text_frame
    tf_msg.word_wrap = True
    tf_msg.margin_left = tf_msg.margin_top = tf_msg.margin_right = tf_msg.margin_bottom = 0
    p_m1 = tf_msg.paragraphs[0]
    p_m1.text = "“The goal is not to fill every hour."
    p_m1.font.name = FONT_HEADING
    p_m1.font.size = Pt(18)
    p_m1.font.bold = True
    p_m1.font.color.rgb = COLOR_WHITE
    p_m1.space_after = Pt(6)

    p_m2 = tf_msg.add_paragraph()
    p_m2.text = "The goal is to use the right hours well.”"
    p_m2.font.name = FONT_HEADING
    p_m2.font.size = Pt(18)
    p_m2.font.bold = True
    p_m2.font.color.rgb = COLOR_GOLD

    # RIGHT SIDE: Balanced 3-column orbit layout
    # Center Banner
    center_banner = add_card(slide1, Inches(7.0), Inches(0.55), Inches(5.533), Inches(0.68), fill_color=COLOR_WHITE, border_color=COLOR_BLUE, border_width=2)
    tf_cb = center_banner.text_frame
    tf_cb.vertical_anchor = MSO_ANCHOR.MIDDLE
    pcb1 = tf_cb.paragraphs[0]
    pcb1.text = "THE COLLEGE STUDENT ECOSYSTEM"
    pcb1.alignment = PP_ALIGN.CENTER
    pcb1.font.name = FONT_HEADING
    pcb1.font.size = Pt(13)
    pcb1.font.bold = True
    pcb1.font.color.rgb = COLOR_NAVY
    pcb2 = tf_cb.add_paragraph()
    pcb2.text = "Balancing academic excellence, health, relationships & personal growth"
    pcb2.alignment = PP_ALIGN.CENTER
    pcb2.font.name = FONT_BODY
    pcb2.font.size = Pt(10)
    pcb2.font.color.rgb = COLOR_MUTED

    # 6 Organized Cards in a 2x3 Grid
    orbit_items = [
        {"tag": "CLASSES", "title": "Lectures & Labs", "desc": "Active participation & notes", "x": Inches(7.0), "y": Inches(1.4), "w": Inches(2.65), "h": Inches(1.35), "color": COLOR_BLUE, "bg": COLOR_BLUE_BG},
        {"tag": "ASSIGNMENTS", "title": "Submissions & Projects", "desc": "Continuous course deadlines", "x": Inches(9.883), "y": Inches(1.4), "w": Inches(2.65), "h": Inches(1.35), "color": COLOR_ORANGE, "bg": COLOR_ORANGE_BG},
        {"tag": "EXAMS", "title": "Tests & Midterms", "desc": "Structured revision sprints", "x": Inches(7.0), "y": Inches(2.95), "w": Inches(2.65), "h": Inches(1.35), "color": COLOR_RED, "bg": COLOR_RED_BG},
        {"tag": "SLEEP", "title": "7–8 Hrs Recovery", "desc": "Non-negotiable brain reset", "x": Inches(9.883), "y": Inches(2.95), "w": Inches(2.65), "h": Inches(1.35), "color": COLOR_BLUE, "bg": COLOR_BLUE_BG},
        {"tag": "HOBBIES", "title": "Sports & Passions", "desc": "De-stressing & creative fuel", "x": Inches(7.0), "y": Inches(4.50), "w": Inches(2.65), "h": Inches(1.35), "color": COLOR_ORANGE, "bg": COLOR_ORANGE_BG},
        {"tag": "FRIENDS", "title": "Social & Campus Life", "desc": "Community & peer support", "x": Inches(9.883), "y": Inches(4.50), "w": Inches(2.65), "h": Inches(1.35), "color": COLOR_GREEN, "bg": COLOR_GREEN_BG},
    ]

    for item in orbit_items:
        card = add_card(slide1, item["x"], item["y"], item["w"], item["h"], fill_color=COLOR_WHITE, border_color=item["color"], border_width=1.5)
        
        # Tag Badge
        add_badge(slide1, item["x"] + Inches(0.15), item["y"] + Inches(0.12), item["w"] - Inches(0.3), Inches(0.28), item["tag"], bg_color=item["bg"], text_color=item["color"], font_size=9)
        
        tbox = slide1.shapes.add_textbox(item["x"] + Inches(0.1), item["y"] + Inches(0.46), item["w"] - Inches(0.2), Inches(0.8))
        tft = tbox.text_frame
        tft.word_wrap = True
        tft.margin_left = tft.margin_top = tft.margin_right = tft.margin_bottom = 0
        pt1 = tft.paragraphs[0]
        pt1.text = item["title"]
        pt1.alignment = PP_ALIGN.CENTER
        pt1.font.name = FONT_HEADING
        pt1.font.size = Pt(12)
        pt1.font.bold = True
        pt1.font.color.rgb = COLOR_TEXT_BLACK
        
        pt2 = tft.add_paragraph()
        pt2.text = item["desc"]
        pt2.alignment = PP_ALIGN.CENTER
        pt2.font.name = FONT_BODY
        pt2.font.size = Pt(10)
        pt2.font.color.rgb = COLOR_MUTED
        pt2.space_before = Pt(3)

    # Bottom Foundation Bar
    bottom_bar = add_card(slide1, Inches(0.8), Inches(6.45), Inches(11.733), Inches(0.62), fill_color=COLOR_WHITE, border_color=COLOR_BORDER, border_width=1)
    tf_bb = bottom_bar.text_frame
    tf_bb.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_bb = tf_bb.paragraphs[0]
    p_bb.text = "BALANCE   •   FOCUS   •   FOLLOW-THROUGH"
    p_bb.alignment = PP_ALIGN.CENTER
    p_bb.font.name = FONT_HEADING
    p_bb.font.size = Pt(14)
    p_bb.font.bold = True
    p_bb.font.color.rgb = COLOR_NAVY

    # =========================================================================
    # SLIDE 2: WHAT IS TIME MANAGEMENT?
    # =========================================================================
    slide2 = prs.slides.add_slide(blank_layout)
    set_slide_background(slide2)

    add_header(
        slide2,
        "CORE CONCEPT",
        "WHAT IS TIME MANAGEMENT?",
        "Decide what to do  →  When to do it  →  Actually do it."
    )

    step_data = [
        {
            "num": "STEP 01",
            "title": "PLAN",
            "subtitle": "“Decide what needs to be done.”",
            "badge": "LIST & MAP",
            "accent": COLOR_BLUE,
            "badge_bg": COLOR_BLUE_BG,
            "details": ["• List realistic tasks for the day", "• Group by classes and upcoming deadlines", "• Keep the daily master list simple"]
        },
        {
            "num": "STEP 02",
            "title": "PRIORITIZE",
            "subtitle": "“Do important tasks first.”",
            "badge": "RANK & SELECT",
            "accent": COLOR_ORANGE,
            "badge_bg": COLOR_ORANGE_BG,
            "details": ["• Identify the top 3 high-impact items", "• Distinguish urgent vs important work", "• Protect high-energy morning hours"]
        },
        {
            "num": "STEP 03",
            "title": "ACT",
            "subtitle": "“Start and finish the task.”",
            "badge": "EXECUTE & FINISH",
            "accent": COLOR_GREEN,
            "badge_bg": COLOR_GREEN_BG,
            "details": ["• Overcome initial friction: start 5 mins", "• Eliminate phone and tab distractions", "• Cross off the task and move forward"]
        }
    ]

    card_w = Inches(3.6)
    card_h = Inches(3.55)
    card_y = Inches(2.05)

    for i, step in enumerate(step_data):
        card_x = Inches(0.8) + i * Inches(4.066)
        add_card(slide2, card_x, card_y, card_w, card_h, fill_color=COLOR_WHITE, border_color=step["accent"], border_width=2)
        
        header_banner = add_card(slide2, card_x + Inches(0.25), card_y + Inches(0.2), card_w - Inches(0.5), Inches(0.4), fill_color=step["badge_bg"], border_color=None)
        tf_hb = header_banner.text_frame
        tf_hb.vertical_anchor = MSO_ANCHOR.MIDDLE
        p_hb = tf_hb.paragraphs[0]
        p_hb.text = f"{step['num']}  |  {step['badge']}"
        p_hb.font.name = FONT_HEADING
        p_hb.font.size = Pt(11)
        p_hb.font.bold = True
        p_hb.font.color.rgb = step["accent"]
        p_hb.alignment = PP_ALIGN.CENTER

        title_box = slide2.shapes.add_textbox(card_x + Inches(0.2), card_y + Inches(0.72), card_w - Inches(0.4), Inches(0.5))
        tf_tb = title_box.text_frame
        tf_tb.word_wrap = True
        tf_tb.margin_left = tf_tb.margin_top = tf_tb.margin_right = tf_tb.margin_bottom = 0
        p_t = tf_tb.paragraphs[0]
        p_t.text = step['title']
        p_t.alignment = PP_ALIGN.CENTER
        p_t.font.name = FONT_HEADING
        p_t.font.size = Pt(24)
        p_t.font.bold = True
        p_t.font.color.rgb = COLOR_TEXT_BLACK

        sub_tbox = slide2.shapes.add_textbox(card_x + Inches(0.2), card_y + Inches(1.22), card_w - Inches(0.4), Inches(0.5))
        tf_stb = sub_tbox.text_frame
        tf_stb.word_wrap = True
        tf_stb.margin_left = tf_stb.margin_top = tf_stb.margin_right = tf_stb.margin_bottom = 0
        p_sub = tf_stb.paragraphs[0]
        p_sub.text = step["subtitle"]
        p_sub.alignment = PP_ALIGN.CENTER
        p_sub.font.name = FONT_BODY
        p_sub.font.size = Pt(12)
        p_sub.font.bold = True
        p_sub.font.color.rgb = step["accent"]

        bullet_box = slide2.shapes.add_textbox(card_x + Inches(0.3), card_y + Inches(1.85), card_w - Inches(0.6), Inches(1.5))
        tf_bl = bullet_box.text_frame
        tf_bl.word_wrap = True
        tf_bl.margin_left = tf_bl.margin_top = tf_bl.margin_right = tf_bl.margin_bottom = 0
        for j, pt in enumerate(step["details"]):
            p_bl = tf_bl.paragraphs[0] if j == 0 else tf_bl.add_paragraph()
            p_bl.text = pt
            p_bl.font.name = FONT_BODY
            p_bl.font.size = Pt(12)
            p_bl.font.color.rgb = COLOR_MUTED
            p_bl.space_before = Pt(8)

        if i < 2:
            arrow_x = card_x + card_w + Inches(0.08)
            arrow_lbl = slide2.shapes.add_textbox(arrow_x, card_y + Inches(1.4), Inches(0.4), Inches(0.6))
            tf_a = arrow_lbl.text_frame
            tf_a.margin_left = tf_a.margin_top = tf_a.margin_right = tf_a.margin_bottom = 0
            pa = tf_a.paragraphs[0]
            pa.text = "→"
            pa.alignment = PP_ALIGN.CENTER
            pa.font.name = FONT_HEADING
            pa.font.size = Pt(28)
            pa.font.bold = True
            pa.font.color.rgb = COLOR_MUTED_LIGHT

    flow_card = add_card(slide2, Inches(0.8), Inches(5.75), Inches(11.733), Inches(0.52), fill_color=COLOR_WHITE, border_color=COLOR_BORDER, border_width=1)
    tf_fc = flow_card.text_frame
    tf_fc.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_fc = tf_fc.paragraphs[0]
    p_fc.text = "THE EXECUTION CHAIN:   PLAN  →  PRIORITIZE  →  ACT  →  COMPLETE [✓]"
    p_fc.alignment = PP_ALIGN.CENTER
    p_fc.font.name = FONT_HEADING
    p_fc.font.size = Pt(13)
    p_fc.font.bold = True
    p_fc.font.color.rgb = COLOR_NAVY

    key_msg = add_card(slide2, Inches(0.8), Inches(6.42), Inches(11.733), Inches(0.65), fill_color=COLOR_NAVY, border_color=None)
    tf_km = key_msg.text_frame
    tf_km.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_km = tf_km.paragraphs[0]
    p_km.text = "KEY TAKEAWAY:  “A timetable is only a plan. Action is what makes it useful.”"
    p_km.alignment = PP_ALIGN.CENTER
    p_km.font.name = FONT_HEADING
    p_km.font.size = Pt(14)
    p_km.font.bold = True
    p_km.font.color.rgb = COLOR_GOLD

    # =========================================================================
    # SLIDE 3: THE PROBLEM: WHY TIMETABLES FAIL
    # =========================================================================
    slide3 = prs.slides.add_slide(blank_layout)
    set_slide_background(slide3)

    add_header(
        slide3,
        "REALITY CHECK",
        "THE PROBLEM: WHY TIMETABLES FAIL",
        "Making a timetable is easy. Following it is hard.",
        tag_bg=COLOR_RED_BG,
        tag_color=COLOR_RED
    )

    problems = [
        {
            "num": "FLAW #01",
            "tag": "OVERLOAD",
            "title": "UNREALISTIC PLANS",
            "impact": "Too many tasks → impossible day",
            "sub": "Over-scheduling 14 hours without factoring human limits."
        },
        {
            "num": "FLAW #02",
            "tag": "DELAY",
            "title": "PROCRASTINATION",
            "impact": "“I’ll do it later.” → deadline stress",
            "sub": "Waiting for 'perfect mood' until midnight panic takes over."
        },
        {
            "num": "FLAW #03",
            "tag": "SCREEN TRAP",
            "title": "DISTRACTIONS",
            "impact": "Phone / reels / games → lost time",
            "sub": "A quick 2-minute break secretly turns into 50 lost minutes."
        },
        {
            "num": "FLAW #04",
            "tag": "ZERO BUFFER",
            "title": "NO FLEXIBILITY",
            "impact": "One missed task → whole plan breaks",
            "sub": "Zero buffer time causes a minor delay to ruin the entire day."
        },
        {
            "num": "FLAW #05",
            "tag": "EXHAUSTION",
            "title": "BURNOUT",
            "impact": "No breaks → tired + low focus",
            "sub": "Studying without scheduled breaks creates intense brain fog."
        }
    ]

    p_w = Inches(2.21)
    p_gap = Inches(0.17)
    p_y = Inches(2.05)
    p_h = Inches(3.2)

    for i, prob in enumerate(problems):
        px = Inches(0.8) + i * (p_w + p_gap)
        add_card(slide3, px, p_y, p_w, p_h, fill_color=COLOR_WHITE, border_color=COLOR_RED, border_width=1.5)
        
        b_num = add_card(slide3, px + Inches(0.15), p_y + Inches(0.15), p_w - Inches(0.3), Inches(0.32), fill_color=COLOR_RED_BG, border_color=None)
        tf_bn = b_num.text_frame
        tf_bn.vertical_anchor = MSO_ANCHOR.MIDDLE
        p_bn = tf_bn.paragraphs[0]
        p_bn.text = prob["num"]
        p_bn.font.name = FONT_HEADING
        p_bn.font.size = Pt(10)
        p_bn.font.bold = True
        p_bn.font.color.rgb = COLOR_RED
        p_bn.alignment = PP_ALIGN.CENTER

        stag = add_card(slide3, px + Inches(0.3), p_y + Inches(0.55), p_w - Inches(0.6), Inches(0.28), fill_color=RGBColor(0xF5, 0xF5, 0xF7), border_color=None)
        tf_st = stag.text_frame
        tf_st.vertical_anchor = MSO_ANCHOR.MIDDLE
        p_st = tf_st.paragraphs[0]
        p_st.text = prob["tag"]
        p_st.font.name = FONT_HEADING
        p_st.font.size = Pt(9)
        p_st.font.bold = True
        p_st.font.color.rgb = COLOR_MUTED
        p_st.alignment = PP_ALIGN.CENTER

        t_box = slide3.shapes.add_textbox(px + Inches(0.1), p_y + Inches(0.95), p_w - Inches(0.2), Inches(0.55))
        tf_t = t_box.text_frame
        tf_t.word_wrap = True
        tf_t.margin_left = tf_t.margin_top = tf_t.margin_right = tf_t.margin_bottom = 0
        p_t = tf_t.paragraphs[0]
        p_t.text = prob["title"]
        p_t.alignment = PP_ALIGN.CENTER
        p_t.font.name = FONT_HEADING
        p_t.font.size = Pt(12)
        p_t.font.bold = True
        p_t.font.color.rgb = COLOR_TEXT_BLACK

        imp_box = slide3.shapes.add_textbox(px + Inches(0.12), p_y + Inches(1.58), p_w - Inches(0.24), Inches(0.72))
        tf_imp = imp_box.text_frame
        tf_imp.word_wrap = True
        tf_imp.margin_left = tf_imp.margin_top = tf_imp.margin_right = tf_imp.margin_bottom = 0
        p_imp = tf_imp.paragraphs[0]
        p_imp.text = prob["impact"]
        p_imp.alignment = PP_ALIGN.CENTER
        p_imp.font.name = FONT_BODY
        p_imp.font.size = Pt(11)
        p_imp.font.bold = True
        p_imp.font.color.rgb = COLOR_RED

        desc_box = slide3.shapes.add_textbox(px + Inches(0.12), p_y + Inches(2.35), p_w - Inches(0.24), Inches(0.75))
        tf_d = desc_box.text_frame
        tf_d.word_wrap = True
        tf_d.margin_left = tf_d.margin_top = tf_d.margin_right = tf_d.margin_bottom = 0
        p_d = tf_d.paragraphs[0]
        p_d.text = prob["sub"]
        p_d.alignment = PP_ALIGN.CENTER
        p_d.font.name = FONT_BODY
        p_d.font.size = Pt(10)
        p_d.font.color.rgb = COLOR_MUTED

    ce_container = add_card(slide3, Inches(0.8), Inches(5.45), Inches(11.733), Inches(0.95), fill_color=COLOR_NAVY, border_color=None)
    
    pill_w = Inches(2.8)
    pill_h = Inches(0.55)
    pill_y = Inches(5.65)

    p1 = add_card(slide3, Inches(1.2), pill_y, pill_w, pill_h, fill_color=RGBColor(0x1B, 0x3B, 0x68), border_color=COLOR_BORDER)
    tf_p1 = p1.text_frame
    tf_p1.vertical_anchor = MSO_ANCHOR.MIDDLE
    pp1 = tf_p1.paragraphs[0]
    pp1.text = "[ PLAN ]  “PERFECT TIMETABLE”"
    pp1.alignment = PP_ALIGN.CENTER
    pp1.font.name = FONT_HEADING
    pp1.font.size = Pt(12)
    pp1.font.bold = True
    pp1.font.color.rgb = COLOR_WHITE

    a1 = slide3.shapes.add_textbox(Inches(4.1), pill_y + Inches(0.06), Inches(0.6), Inches(0.4))
    tf_a1 = a1.text_frame
    pa1 = tf_a1.paragraphs[0]
    pa1.text = "→"
    pa1.alignment = PP_ALIGN.CENTER
    pa1.font.name = FONT_HEADING
    pa1.font.size = Pt(24)
    pa1.font.bold = True
    pa1.font.color.rgb = COLOR_ORANGE

    p2 = add_card(slide3, Inches(4.8), pill_y, pill_w, pill_h, fill_color=RGBColor(0x1B, 0x3B, 0x68), border_color=COLOR_BORDER)
    tf_p2 = p2.text_frame
    tf_p2.vertical_anchor = MSO_ANCHOR.MIDDLE
    pp2 = tf_p2.paragraphs[0]
    pp2.text = "[ GAP ]  “NO ACTION”"
    pp2.alignment = PP_ALIGN.CENTER
    pp2.font.name = FONT_HEADING
    pp2.font.size = Pt(12)
    pp2.font.bold = True
    pp2.font.color.rgb = COLOR_GOLD

    a2 = slide3.shapes.add_textbox(Inches(7.7), pill_y + Inches(0.06), Inches(0.6), Inches(0.4))
    tf_a2 = a2.text_frame
    pa2 = tf_a2.paragraphs[0]
    pa2.text = "→"
    pa2.alignment = PP_ALIGN.CENTER
    pa2.font.name = FONT_HEADING
    pa2.font.size = Pt(24)
    pa2.font.bold = True
    pa2.font.color.rgb = COLOR_RED

    p3 = add_card(slide3, Inches(8.4), pill_y, pill_w, pill_h, fill_color=RGBColor(0x3B, 0x1A, 0x22), border_color=COLOR_RED)
    tf_p3 = p3.text_frame
    tf_p3.vertical_anchor = MSO_ANCHOR.MIDDLE
    pp3 = tf_p3.paragraphs[0]
    pp3.text = "[ RESULT ]  “STRESS & GUILT”"
    pp3.alignment = PP_ALIGN.CENTER
    pp3.font.name = FONT_HEADING
    pp3.font.size = Pt(12)
    pp3.font.bold = True
    pp3.font.color.rgb = RGBColor(0xFF, 0x8A, 0x8A)

    bot_box = slide3.shapes.add_textbox(Inches(0.8), Inches(6.52), Inches(11.733), Inches(0.5))
    tf_bb = bot_box.text_frame
    tf_bb.word_wrap = True
    tf_bb.margin_left = tf_bb.margin_top = tf_bb.margin_right = tf_bb.margin_bottom = 0
    p_bb = tf_bb.paragraphs[0]
    p_bb.text = "✦ The problem is not making a timetable. The problem is making a timetable that is difficult to follow."
    p_bb.alignment = PP_ALIGN.CENTER
    p_bb.font.name = FONT_HEADING
    p_bb.font.size = Pt(13)
    p_bb.font.bold = True
    p_bb.font.color.rgb = COLOR_TEXT_BLACK

    # =========================================================================
    # SLIDE 4: SIMPLE SOLUTIONS THAT ACTUALLY WORK
    # =========================================================================
    slide4 = prs.slides.add_slide(blank_layout)
    set_slide_background(slide4)

    add_header(
        slide4,
        "ACTIONABLE STRATEGY",
        "SIMPLE SOLUTIONS THAT ACTUALLY WORK",
        "Replace a perfect plan with a small, flexible system.",
        tag_bg=COLOR_GREEN_BG,
        tag_color=COLOR_GREEN
    )

    solutions = [
        {
            "problem": "[X]  Too many tasks on daily list",
            "stat": "3–5",
            "stat_label": "TASKS",
            "solution": "[✓]  Choose only 3–5 important tasks",
            "desc": "Focus on high-leverage priorities that actually move the needle."
        },
        {
            "problem": "[X]  Procrastination & delay",
            "stat": "5 MIN",
            "stat_label": "RULE",
            "solution": "[✓]  Use the 5-Minute Rule",
            "desc": "Commit to working for just 5 minutes. Momentum kicks in automatically."
        },
        {
            "problem": "[X]  Constant phone distractions",
            "stat": "FOCUS",
            "stat_label": "MODE",
            "solution": "[✓]  Keep phone in another room / Focus Mode",
            "desc": "Out of sight, out of mind. Protect your cognitive bandwidth."
        },
        {
            "problem": "[X]  Rigid, back-to-back timetable",
            "stat": "30–60",
            "stat_label": "MIN BUFFER",
            "solution": "[✓]  Leave 30–60 minutes of buffer time",
            "desc": "Absorption space for surprises, delayed buses, or longer assignments."
        },
        {
            "problem": "[X]  Burnout & study fatigue",
            "stat": "25 / 5",
            "stat_label": "POMODORO",
            "solution": "[✓]  25 mins study  +  5 mins break",
            "desc": "Short sprints maintain high mental sharpness all afternoon."
        }
    ]

    row_y_start = Inches(2.02)
    row_h = Inches(0.76)
    row_gap = Inches(0.12)

    for i, sol in enumerate(solutions):
        curr_y = row_y_start + i * (row_h + row_gap)
        
        p_card = add_card(slide4, Inches(0.8), curr_y, Inches(4.3), row_h, fill_color=COLOR_WHITE, border_color=RGBColor(0xF0, 0xC4, 0xC4))
        tf_p = p_card.text_frame
        tf_p.word_wrap = True
        tf_p.margin_left = Inches(0.25)
        tf_p.vertical_anchor = MSO_ANCHOR.MIDDLE
        pp = tf_p.paragraphs[0]
        pp.text = sol["problem"]
        pp.font.name = FONT_BODY
        pp.font.size = Pt(13)
        pp.font.bold = True
        pp.font.color.rgb = COLOR_RED
        pp.alignment = PP_ALIGN.LEFT

        stat_card = add_card(slide4, Inches(5.2), curr_y, Inches(1.7), row_h, fill_color=COLOR_NAVY, border_color=None)
        tf_s = stat_card.text_frame
        tf_s.word_wrap = True
        tf_s.vertical_anchor = MSO_ANCHOR.MIDDLE
        ps1 = tf_s.paragraphs[0]
        ps1.text = sol["stat"]
        ps1.alignment = PP_ALIGN.CENTER
        ps1.font.name = FONT_HEADING
        ps1.font.size = Pt(15)
        ps1.font.bold = True
        ps1.font.color.rgb = COLOR_GOLD

        ps2 = tf_s.add_paragraph()
        ps2.text = sol["stat_label"]
        ps2.alignment = PP_ALIGN.CENTER
        ps2.font.name = FONT_HEADING
        ps2.font.size = Pt(9)
        ps2.font.bold = True
        ps2.font.color.rgb = COLOR_WHITE

        arr_box = slide4.shapes.add_textbox(Inches(6.98), curr_y + Inches(0.18), Inches(0.45), Inches(0.4))
        tf_a = arr_box.text_frame
        tf_a.margin_left = tf_a.margin_top = tf_a.margin_right = tf_a.margin_bottom = 0
        pa = tf_a.paragraphs[0]
        pa.text = "→"
        pa.alignment = PP_ALIGN.CENTER
        pa.font.name = FONT_HEADING
        pa.font.size = Pt(22)
        pa.font.bold = True
        pa.font.color.rgb = COLOR_GREEN

        s_card = add_card(slide4, Inches(7.5), curr_y, Inches(5.033), row_h, fill_color=COLOR_WHITE, border_color=RGBColor(0xB5, 0xE2, 0xC8), border_width=1.5)
        tf_sol = s_card.text_frame
        tf_sol.word_wrap = True
        tf_sol.margin_left = Inches(0.2)
        tf_sol.vertical_anchor = MSO_ANCHOR.MIDDLE
        psol1 = tf_sol.paragraphs[0]
        psol1.text = sol["solution"]
        psol1.font.name = FONT_HEADING
        psol1.font.size = Pt(13)
        psol1.font.bold = True
        psol1.font.color.rgb = COLOR_GREEN

        psol2 = tf_sol.add_paragraph()
        psol2.text = sol["desc"]
        psol2.font.name = FONT_BODY
        psol2.font.size = Pt(10)
        psol2.font.color.rgb = COLOR_MUTED

    bot_loop = add_card(slide4, Inches(0.8), Inches(6.48), Inches(11.733), Inches(0.62), fill_color=COLOR_WHITE, border_color=COLOR_BORDER, border_width=1)
    tf_bl = bot_loop.text_frame
    tf_bl.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_bl = tf_bl.paragraphs[0]
    p_bl.text = "THE WINNING HABIT:   SMALL PLAN  →  START  →  FOCUS  →  BREAK  →  COMPLETE [✓]"
    p_bl.alignment = PP_ALIGN.CENTER
    p_bl.font.name = FONT_HEADING
    p_bl.font.size = Pt(13)
    p_bl.font.bold = True
    p_bl.font.color.rgb = COLOR_NAVY

    # =========================================================================
    # SLIDE 5: PRACTICAL COLLEGE DAY
    # =========================================================================
    slide5 = prs.slides.add_slide(blank_layout)
    set_slide_background(slide5)

    add_header(
        slide5,
        "DAILY BLUEPRINT",
        "A SIMPLE COLLEGE DAY YOU CAN ACTUALLY FOLLOW",
        "Use blocks, not a minute-by-minute timetable. (Realistic example, not a rigid prison)"
    )

    sched_title = add_card(slide5, Inches(0.8), Inches(1.95), Inches(5.8), Inches(0.38), fill_color=COLOR_BLUE_BG, border_color=None)
    tf_st = sched_title.text_frame
    tf_st.vertical_anchor = MSO_ANCHOR.MIDDLE
    p_st = tf_st.paragraphs[0]
    p_st.text = "EXAMPLE TIME-BLOCK ROUTINE (FLEXIBLE)"
    p_st.font.name = FONT_HEADING
    p_st.font.size = Pt(11)
    p_st.font.bold = True
    p_st.font.color.rgb = COLOR_BLUE
    p_st.alignment = PP_ALIGN.CENTER

    schedule_blocks = [
        {"time": "8:00 – 1:00", "tag": "CLASSES", "title": "College / Classes", "note": "Lectures, labs, active notes", "color": COLOR_BLUE, "bg": COLOR_BLUE_BG},
        {"time": "2:00 – 4:00", "tag": "STUDY",   "title": "Assignments & Study", "note": "Top 2 priority submissions", "color": COLOR_ORANGE, "bg": COLOR_ORANGE_BG},
        {"time": "5:00 – 6:00", "tag": "RESET",   "title": "Exercise / Hobby", "note": "Gym, sports, music, or walk", "color": COLOR_GREEN, "bg": COLOR_GREEN_BG},
        {"time": "7:00 – 8:00", "tag": "REVIEW",  "title": "Revision", "note": "Review tough concepts (60 min)", "color": COLOR_BLUE, "bg": COLOR_BLUE_BG},
        {"time": "8:00+ PM",   "tag": "RECHARGE","title": "Dinner + Relax", "note": "Friends, dinner, quality sleep", "color": COLOR_NAVY, "bg": RGBColor(0xEE, 0xF1, 0xF6)}
    ]

    sb_y = Inches(2.40)
    sb_h = Inches(0.58)
    sb_gap = Inches(0.08)

    for i, sb in enumerate(schedule_blocks):
        cy = sb_y + i * (sb_h + sb_gap)
        scard = add_card(slide5, Inches(0.8), cy, Inches(5.8), sb_h, fill_color=COLOR_WHITE, border_color=sb["color"], border_width=1.5)
        
        tb = add_card(slide5, Inches(0.95), cy + Inches(0.09), Inches(1.5), Inches(0.40), fill_color=sb["bg"], border_color=None)
        tf_tb = tb.text_frame
        tf_tb.vertical_anchor = MSO_ANCHOR.MIDDLE
        ptb = tf_tb.paragraphs[0]
        ptb.text = sb["time"]
        ptb.alignment = PP_ALIGN.CENTER
        ptb.font.name = FONT_HEADING
        ptb.font.size = Pt(11)
        ptb.font.bold = True
        ptb.font.color.rgb = sb["color"]

        tc = slide5.shapes.add_textbox(Inches(2.55), cy + Inches(0.04), Inches(3.9), Inches(0.50))
        tf_tc = tc.text_frame
        tf_tc.word_wrap = True
        tf_tc.margin_left = tf_tc.margin_top = tf_tc.margin_right = tf_tc.margin_bottom = 0
        ptc1 = tf_tc.paragraphs[0]
        ptc1.text = f"{sb['title']}  [{sb['tag']}]"
        ptc1.font.name = FONT_HEADING
        ptc1.font.size = Pt(12)
        ptc1.font.bold = True
        ptc1.font.color.rgb = COLOR_TEXT_BLACK

        ptc2 = tf_tc.add_paragraph()
        ptc2.text = sb["note"]
        ptc2.font.name = FONT_BODY
        ptc2.font.size = Pt(10)
        ptc2.font.color.rgb = COLOR_MUTED

    comp_x = Inches(6.9)
    comp_w = Inches(5.633)

    card_dont = add_card(slide5, comp_x, Inches(1.95), comp_w, Inches(1.6), fill_color=COLOR_RED_BG, border_color=COLOR_RED, border_width=2)
    tf_dont = card_dont.text_frame
    tf_dont.word_wrap = True
    tf_dont.margin_left = Inches(0.25)
    tf_dont.margin_top = Inches(0.16)
    tf_dont.margin_right = Inches(0.25)
    p_d1 = tf_dont.paragraphs[0]
    p_d1.text = "DON’T DO THIS  [X]"
    p_d1.font.name = FONT_HEADING
    p_d1.font.size = Pt(15)
    p_d1.font.bold = True
    p_d1.font.color.rgb = COLOR_RED

    p_d2 = tf_dont.add_paragraph()
    p_d2.text = "“Huge timetable  →  miss one task  →  give up”"
    p_d2.font.name = FONT_HEADING
    p_d2.font.size = Pt(13)
    p_d2.font.bold = True
    p_d2.font.color.rgb = COLOR_TEXT_BLACK
    p_d2.space_before = Pt(4)

    p_d3 = tf_dont.add_paragraph()
    p_d3.text = "Scheduling 15 back-to-back items sets you up for guilt when life inevitably happens."
    p_d3.font.name = FONT_BODY
    p_d3.font.size = Pt(11)
    p_d3.font.color.rgb = COLOR_MUTED
    p_d3.space_before = Pt(3)

    card_do = add_card(slide5, comp_x, Inches(3.68), comp_w, Inches(1.6), fill_color=COLOR_GREEN_BG, border_color=COLOR_GREEN, border_width=2)
    tf_do = card_do.text_frame
    tf_do.word_wrap = True
    tf_do.margin_left = Inches(0.25)
    tf_do.margin_top = Inches(0.16)
    tf_do.margin_right = Inches(0.25)
    p_o1 = tf_do.paragraphs[0]
    p_o1.text = "DO THIS  [✓]"
    p_o1.font.name = FONT_HEADING
    p_o1.font.size = Pt(15)
    p_o1.font.bold = True
    p_o1.font.color.rgb = COLOR_GREEN

    p_o2 = tf_do.add_paragraph()
    p_o2.text = "“Small plan  →  complete  →  track  →  continue”"
    p_o2.font.name = FONT_HEADING
    p_o2.font.size = Pt(13)
    p_o2.font.bold = True
    p_o2.font.color.rgb = COLOR_TEXT_BLACK
    p_o2.space_before = Pt(4)

    p_o3 = tf_do.add_paragraph()
    p_o3.text = "Focus on completing 3 solid tasks in dedicated blocks. Consistent momentum beats perfection."
    p_o3.font.name = FONT_BODY
    p_o3.font.size = Pt(11)
    p_o3.font.color.rgb = COLOR_MUTED
    p_o3.space_before = Pt(3)

    bot_navy = add_card(slide5, Inches(0.8), Inches(5.42), Inches(11.733), Inches(1.5), fill_color=COLOR_NAVY, border_color=None)
    
    loop_badge = add_card(slide5, Inches(1.1), Inches(5.58), Inches(11.133), Inches(0.38), fill_color=RGBColor(0x1B, 0x3B, 0x68), border_color=None)
    tf_lb = loop_badge.text_frame
    tf_lb.vertical_anchor = MSO_ANCHOR.MIDDLE
    plb = tf_lb.paragraphs[0]
    plb.text = "THE CONTINUOUS HABIT:   PLAN  →  DO  →  TRACK  →  IMPROVE"
    plb.alignment = PP_ALIGN.CENTER
    plb.font.name = FONT_HEADING
    plb.font.size = Pt(12)
    plb.font.bold = True
    plb.font.color.rgb = COLOR_GOLD

    final_box = slide5.shapes.add_textbox(Inches(1.1), Inches(6.12), Inches(11.133), Inches(0.65))
    tf_fb = final_box.text_frame
    tf_fb.word_wrap = True
    tf_fb.margin_left = tf_fb.margin_top = tf_fb.margin_right = tf_fb.margin_bottom = 0
    pfb1 = tf_fb.paragraphs[0]
    pfb1.text = "“Time management is not about filling every minute. It is about using your time for what matters.”"
    pfb1.alignment = PP_ALIGN.CENTER
    pfb1.font.name = FONT_HEADING
    pfb1.font.size = Pt(14)
    pfb1.font.bold = True
    pfb1.font.color.rgb = COLOR_WHITE

    # Save presentation
    output_path = "/Users/madhusudhan/Desktop/Work-Space/NammaMove_AI/Time_Management_For_College_Students.pptx"
    prs.save(output_path)
    print(f"Presentation regenerated successfully to: {output_path}")

if __name__ == "__main__":
    create_presentation()
