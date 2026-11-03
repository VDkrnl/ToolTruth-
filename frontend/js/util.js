/**
 * frontend/js/util.js  — Shared DOM-safety utilities (C-07)
 *
 * Import with:
 *   import { escapeHtml, setTextById, createElement } from '../js/util.js';
 * or include as a plain <script> tag before any script that uses these helpers.
 */

/**
 * Escape a string so it is safe to interpolate into HTML.
 * @param {*} str  Any value; non-strings are coerced via String().
 * @returns {string} HTML-escaped string.
 */
export function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

/**
 * Set the textContent of a DOM element by id (null-safe).
 * @param {string} id   Element id.
 * @param {string} text Text to set.
 */
export function setTextById(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

/**
 * Create a DOM element with optional text content and class name.
 * @param {string} tag       Tag name.
 * @param {string} [text]    textContent.
 * @param {string} [cls]     className.
 * @returns {HTMLElement}
 */
export function createElement(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
