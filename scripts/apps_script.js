const WEBHOOK_URL = "https://your-domain.com/webhook/sheets";
const WEBHOOK_SECRET = "your-super-secret-key-here";

function handleEdit(e) {
  try {
    if (!e || !e.range) {
      Logger.log("Событие не содержит range");
      return;
    }

    Utilities.sleep(3000)

    const sheet = e.source.getActiveSheet();
    const row = e.range.getRow();
    if (row === 1) return;

    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    const values = sheet.getRange(row, 1, 1, sheet.getLastColumn()).getValues()[0];

    const data = {};
    headers.forEach((header, i) => {
      data[header.trim().toLowerCase()] = values[i] ?? "";
    });

    const name = data.name || "";
    const phone = String(data.phone || "");
    const email = String(data.email || "");
    const budget = parseFloat(data.budget) || 0;
    const amoDealId = String(data.amo_deal_id || "");

    if (!name && !phone && !email) {
      Logger.log(`Пустая строка ${row} — пропуск`);
      return;
    }

    const payload = {
      row_index: row,
      data: {
        name,
        phone,
        email,
        budget,
        amo_deal_id: amoDealId,
        external_id: null
      }
    };

    const options = {
      method: "post",
      contentType: "application/json",
      headers: {
        "X-Webhook-Secret": WEBHOOK_SECRET
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(WEBHOOK_URL, options);
    const code = response.getResponseCode();
    const text = response.getContentText();

    if (code >= 200 && code < 300) {
      Logger.log(`Вебхук успешно отправлен для строки ${row}: ${code}`);
    } else {
      Logger.log(`Ошибка при отправке строки ${row}: ${code} ${text}`);
    }

  } catch (err) {
    Logger.log(`Exception: ${err.message}`);
  }
}