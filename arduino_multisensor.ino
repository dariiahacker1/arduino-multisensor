#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "DHT.h"

LiquidCrystal_I2C lcd(0x27, 16, 2); 

// Pins
const int micPin     = A0;   // KY-037 analog
const int waterPin   = A1;   // Water sensor analog
const int gasPin     = A2;   // MQ-2 analog OUT
const int vibPin     = 4;    // SW-1801P digital OUT
const int pirPin     = 2;    // HC-SR501 OUT
const int ledPin     = 13;   // Built-in LED
const int extLedPin  = 3;    // External LED (motion only)

// DHT11 on D5
#define DHTPIN 5
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// DHT read throttle
unsigned long lastDhtMs = 0;
const unsigned long DHT_PERIOD = 2000;
float tempC = NAN, hum = NAN;

// Rotation timing
const unsigned long PAGE_MS = 3000; // 3s per view
unsigned long lastPageMs = 0;
int page = 0; // 0: Gas+Sound, 1: Sound+Water, 2: Water+Gas

unsigned long lastPrint = 0;
const unsigned long PRINT_PERIOD = 1000;  // print every 1s

void setup() {
  Serial.begin(115200);           // <<< for Python/Serial Monitor

  lcd.init();
  lcd.backlight();

  pinMode(pirPin, INPUT);
  pinMode(vibPin, INPUT);
  pinMode(ledPin, OUTPUT);
  pinMode(extLedPin, OUTPUT);
  digitalWrite(ledPin, LOW);
  digitalWrite(extLedPin, LOW);

  dht.begin();

  lcd.setCursor(0, 0);
  lcd.print("Sensors Ready");
  delay(800);
  lcd.clear();

  lastPageMs = millis();
}

void loop() {
  // Read analog sensors
  int soundValue  = analogRead(micPin);
  int waterValue  = analogRead(waterPin);
  int gasValue    = analogRead(gasPin);

  // PIR motion detection
  bool motion  = (digitalRead(pirPin) == HIGH);  // HC-SR501 is usually active-HIGH
  bool vibration  = (digitalRead(vibPin) == LOW);  // SW-1801P

  // DHT every ~2s
  unsigned long now = millis();
  if (now - lastDhtMs >= DHT_PERIOD) {
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h) && !isnan(t)) { hum = h; tempC = t; }
    lastDhtMs = now;
  }

 if (now - lastPrint >= PRINT_PERIOD) {
  Serial.print("{");
  Serial.print("\"gas\":"); Serial.print(gasValue); Serial.print(",");
  Serial.print("\"sound\":"); Serial.print(soundValue); Serial.print(",");
  Serial.print("\"water\":"); Serial.print(waterValue); Serial.print(",");
  Serial.print("\"temp\":"); Serial.print(tempC); Serial.print(",");
  Serial.print("\"humidity\":"); Serial.print(hum); Serial.print(",");
  Serial.print("\"motion\":"); Serial.print(motion ? 1 : 0); Serial.print(",");
  Serial.print("\"vibration\":"); Serial.print(vibration ? 1 : 0); 
  Serial.println("}");
  lastPrint = now;
}

  // Rotate line 1 every 3s
  if (now - lastPageMs >= PAGE_MS) {
    page = (page + 1) % 3;
    lastPageMs = now;
    lcd.setCursor(0, 0);
    lcd.print("                ");
  }

  // --- Line 1 (rotating sensors) ---
  lcd.setCursor(0, 0);
  switch (page) {
    case 0:
      lcd.print("Gas:"); lcd.print(gasValue);
      lcd.print(" Snd:"); lcd.print(soundValue);
      lcd.print("   ");
      break;
    case 1:
      lcd.print("Snd:"); lcd.print(soundValue);
      lcd.print(" Wtr:"); lcd.print(waterValue);
      lcd.print("   ");
      break;
    case 2:
      lcd.print("Wtr:"); lcd.print(waterValue);
      lcd.print(" Gas:"); lcd.print(gasValue);
      lcd.print("   ");
      break;
  }

  // --- Line 2 (motion or DHT info) ---
  lcd.setCursor(0, 1);
  if (motion) {
    lcd.print("Motion: DETECT ");
  } else if (!isnan(tempC) && !isnan(hum)) {
    lcd.print("T:"); lcd.print(tempC, 1);
    lcd.print((char)223); lcd.print("C H:");
    lcd.print((int)hum); lcd.print("%  ");
  } else {
    lcd.print("Reading DHT... ");
  }

  // --- LED behavior ---
  digitalWrite(extLedPin, motion ? HIGH : LOW);   // external LED → only motion
  digitalWrite(ledPin,    motion ? HIGH : LOW);   // built-in LED mirrors motion

  delay(120);
}