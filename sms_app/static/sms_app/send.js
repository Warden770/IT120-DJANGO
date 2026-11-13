// Live character counter, message preview and contact picker for the Send SMS page.
(function () {
  "use strict";

  var form = document.getElementById("sms-form");
  if (!form) return;

  var maxLength = parseInt(form.dataset.maxLength, 10) || 1600;
  var phone = document.getElementById("id_phone_number");
  var message = document.getElementById("id_message");
  var counter = document.getElementById("counter");
  var previewTo = document.getElementById("preview-to");
  var previewBody = document.getElementById("preview-body");
  var segments = document.getElementById("segments");
  var picker = document.getElementById("contact-picker");

  // Rough estimate: plain ASCII text fits 160 chars/segment (153 when split);
  // anything else (emoji, accents...) is sent as UCS-2: 70 (67 when split).
  function estimateSegments(text) {
    if (!text.length) return { count: 0, perSegment: 160, encoding: "GSM-7" };
    var ascii = /^[\x00-\x7F]*$/.test(text);
    var single = ascii ? 160 : 70;
    var multi = ascii ? 153 : 67;
    var count = text.length <= single ? 1 : Math.ceil(text.length / multi);
    return { count: count, perSegment: text.length <= single ? single : multi, encoding: ascii ? "GSM-7" : "UCS-2" };
  }

  function update() {
    var text = message.value;
    counter.textContent = text.length + " / " + maxLength + " characters";
    counter.classList.toggle("over", text.length > maxLength);

    previewTo.textContent = phone.value.trim() || "—";
    previewBody.textContent = text.trim() || "Your message will appear here.";
    previewBody.classList.toggle("placeholder", !text.trim());

    var info = estimateSegments(text);
    segments.textContent = info.count
      ? "Estimated: " + info.count + " SMS segment" + (info.count > 1 ? "s" : "") +
        " (" + info.encoding + ", " + info.perSegment + " characters each)."
      : "";
  }

  phone.addEventListener("input", update);
  message.addEventListener("input", update);

  if (picker) {
    picker.addEventListener("change", function () {
      if (picker.value) {
        phone.value = picker.value;
        update();
      }
    });
  }

  update();
})();
