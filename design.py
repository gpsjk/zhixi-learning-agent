"""Shared visual system. HTML contains only escaped display text; actions stay native."""
from html import escape
from pathlib import Path
import streamlit as st


def apply_design():
    st.html((Path(__file__).parent / 'assets/style.css').read_text(encoding='utf-8'))


def brand():
    st.html('''<div class="brand"><div class="brand-mark">知</div>
        <div><strong>知错</strong><span>LEARNING STUDIO</span></div></div>
        <div class="brand-note">让每一次复盘，都有回响。</div>''')


def page_header(title, subtitle, kicker='YOUR LEARNING SPACE'):
    st.html(f'<div class="eyebrow"><span></span>{escape(kicker)}</div>')
    st.title(title)
    st.caption(subtitle)


def hero():
    st.html('<section class="welcome-panel"><div class="welcome-copy">'
            '<div class="welcome-label">学习，从理解开始</div>'
            '<h2>整理问题，稳步向前。</h2>'
            '<p>记录一道错题，理解一种方法。让每一次复习都有明确的方向。</p>'
            '</div><div class="welcome-note">记录 · 理解 · 巩固<br><span>建立自己的学习节奏</span></div></section>')


def empty_guide():
    st.html('''<div class="journey"><div><span>01 / CAPTURE</span><h3>留住问题</h3><p>把题目和当时的思路一起记下来。</p></div>
      <div><span>02 / UNDERSTAND</span><h3>看懂错因</h3><p>找到卡住的那一步，重新梳理方法。</p></div>
      <div><span>03 / PRACTICE</span><h3>独立掌握</h3><p>通过复习和追问，把理解变成能力。</p></div></div>''')
