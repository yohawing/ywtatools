using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace YWTA.Link.Unity
{
    internal static class StrictJson
    {
        internal const long MaxSafeInteger = 9007199254740991L;

        internal static Dictionary<string, object> ParseObject(string json, int maxBytes = 64 * 1024)
        {
            if (json == null || Encoding.UTF8.GetByteCount(json) > maxBytes)
            {
                throw new FormatException("JSON is null or exceeds the configured byte limit");
            }
            Parser parser = new Parser(json);
            object value = parser.ParseValue(0);
            parser.RequireEnd();
            return RequireObject(value, "root");
        }

        internal static void ExactFields(Dictionary<string, object> value, params string[] fields)
        {
            if (value.Count != fields.Length)
            {
                throw new FormatException("JSON object has unknown or missing fields");
            }
            foreach (string field in fields)
            {
                if (!value.ContainsKey(field))
                {
                    throw new FormatException("JSON object is missing field: " + field);
                }
            }
        }

        internal static Dictionary<string, object> Object(Dictionary<string, object> value, string field)
        {
            return RequireObject(Get(value, field), field);
        }

        internal static string String(Dictionary<string, object> value, string field)
        {
            object item = Get(value, field);
            if (!(item is string text) || string.IsNullOrWhiteSpace(text))
            {
                throw new FormatException(field + " must be a non-empty string");
            }
            return text;
        }

        internal static long Integer(Dictionary<string, object> value, string field)
        {
            object item = Get(value, field);
            if (!(item is long number) || number < -MaxSafeInteger || number > MaxSafeInteger)
            {
                throw new FormatException(field + " must be a safe integer");
            }
            return number;
        }

        internal static long NonNegativeInteger(Dictionary<string, object> value, string field)
        {
            long number = Integer(value, field);
            if (number < 0) throw new FormatException(field + " must be non-negative");
            return number;
        }

        internal static long PositiveInteger(Dictionary<string, object> value, string field)
        {
            long number = Integer(value, field);
            if (number <= 0) throw new FormatException(field + " must be positive");
            return number;
        }

        internal static double Number(Dictionary<string, object> value, string field)
        {
            object item = Get(value, field);
            double number;
            if (item is long integer)
            {
                number = integer;
            }
            else if (item is double real)
            {
                number = real;
            }
            else
            {
                throw new FormatException(field + " must be a number");
            }
            if (double.IsNaN(number) || double.IsInfinity(number))
            {
                throw new FormatException(field + " must be finite");
            }
            return number;
        }

        internal static bool Boolean(Dictionary<string, object> value, string field)
        {
            object item = Get(value, field);
            if (!(item is bool flag))
            {
                throw new FormatException(field + " must be boolean");
            }
            return flag;
        }

        internal static void Null(Dictionary<string, object> value, string field)
        {
            if (Get(value, field) != null)
            {
                throw new FormatException(field + " must be null");
            }
        }

        internal static List<object> Array(Dictionary<string, object> value, string field)
        {
            object item = Get(value, field);
            if (!(item is List<object> array))
            {
                throw new FormatException(field + " must be an array");
            }
            return array;
        }

        private static object Get(Dictionary<string, object> value, string field)
        {
            if (!value.TryGetValue(field, out object item))
            {
                throw new FormatException("JSON object is missing field: " + field);
            }
            return item;
        }

        private static Dictionary<string, object> RequireObject(object value, string field)
        {
            if (!(value is Dictionary<string, object> result))
            {
                throw new FormatException(field + " must be an object");
            }
            return result;
        }

        private sealed class Parser
        {
            private const int MaxDepth = 32;
            private const int MaxCollection = 1024;
            private const int MaxString = 4096;
            private readonly string _text;
            private int _index;

            internal Parser(string text)
            {
                _text = text;
            }

            internal object ParseValue(int depth)
            {
                if (depth > MaxDepth)
                {
                    throw Error("JSON nesting is too deep");
                }
                SkipWhitespace();
                if (_index >= _text.Length)
                {
                    throw Error("JSON value is missing");
                }
                switch (_text[_index])
                {
                    case '{': return ParseObject(depth + 1);
                    case '[': return ParseArray(depth + 1);
                    case '"': return ParseString();
                    case 't': ReadLiteral("true"); return true;
                    case 'f': ReadLiteral("false"); return false;
                    case 'n': ReadLiteral("null"); return null;
                    default: return ParseNumber();
                }
            }

            internal void RequireEnd()
            {
                SkipWhitespace();
                if (_index != _text.Length)
                {
                    throw Error("JSON contains trailing data");
                }
            }

            private Dictionary<string, object> ParseObject(int depth)
            {
                _index++;
                Dictionary<string, object> result = new Dictionary<string, object>(StringComparer.Ordinal);
                SkipWhitespace();
                if (Take('}'))
                {
                    return result;
                }
                while (true)
                {
                    SkipWhitespace();
                    if (_index >= _text.Length || _text[_index] != '"')
                    {
                        throw Error("JSON object key must be a string");
                    }
                    string key = ParseString();
                    SkipWhitespace();
                    Require(':');
                    if (!result.TryAdd(key, ParseValue(depth)))
                    {
                        throw Error("JSON object contains duplicate keys");
                    }
                    if (result.Count > MaxCollection)
                    {
                        throw Error("JSON object is too large");
                    }
                    SkipWhitespace();
                    if (Take('}'))
                    {
                        return result;
                    }
                    Require(',');
                }
            }

            private List<object> ParseArray(int depth)
            {
                _index++;
                List<object> result = new List<object>();
                SkipWhitespace();
                if (Take(']'))
                {
                    return result;
                }
                while (true)
                {
                    result.Add(ParseValue(depth));
                    if (result.Count > MaxCollection)
                    {
                        throw Error("JSON array is too large");
                    }
                    SkipWhitespace();
                    if (Take(']'))
                    {
                        return result;
                    }
                    Require(',');
                }
            }

            private string ParseString()
            {
                Require('"');
                StringBuilder result = new StringBuilder();
                while (_index < _text.Length)
                {
                    char character = _text[_index++];
                    if (character == '"')
                    {
                        return result.ToString();
                    }
                    if (character < 0x20)
                    {
                        throw Error("JSON string contains a control character");
                    }
                    if (character == '\\')
                    {
                        if (_index >= _text.Length)
                        {
                            throw Error("JSON escape is incomplete");
                        }
                        character = Escape(_text[_index++]);
                    }
                    if (char.IsHighSurrogate(character))
                    {
                        char low;
                        if (_index + 1 < _text.Length && _text[_index] == '\\' && _text[_index + 1] == 'u')
                        {
                            _index += 2;
                            low = ReadUnicode();
                        }
                        else if (_index < _text.Length)
                        {
                            low = _text[_index++];
                        }
                        else
                        {
                            throw Error("JSON string contains an invalid surrogate");
                        }
                        if (!char.IsLowSurrogate(low))
                        {
                            throw Error("JSON string contains an invalid surrogate");
                        }
                        result.Append(character).Append(low);
                    }
                    else if (char.IsLowSurrogate(character))
                    {
                        throw Error("JSON string contains an invalid surrogate");
                    }
                    else
                    {
                        result.Append(character);
                    }
                    if (result.Length > MaxString)
                    {
                        throw Error("JSON string is too long");
                    }
                }
                throw Error("JSON string is unterminated");
            }

            private char Escape(char value)
            {
                switch (value)
                {
                    case '"': return '"';
                    case '\\': return '\\';
                    case '/': return '/';
                    case 'b': return '\b';
                    case 'f': return '\f';
                    case 'n': return '\n';
                    case 'r': return '\r';
                    case 't': return '\t';
                    case 'u': return ReadUnicode();
                    default: throw Error("JSON escape is invalid");
                }
            }

            private char ReadUnicode()
            {
                if (_index + 4 > _text.Length ||
                    !ushort.TryParse(_text.Substring(_index, 4), NumberStyles.HexNumber,
                        CultureInfo.InvariantCulture, out ushort value))
                {
                    throw Error("JSON unicode escape is invalid");
                }
                _index += 4;
                return (char)value;
            }

            private object ParseNumber()
            {
                int start = _index;
                Take('-');
                if (Take('0'))
                {
                    if (_index < _text.Length && char.IsDigit(_text[_index]))
                    {
                        throw Error("JSON number has a leading zero");
                    }
                }
                else
                {
                    RequireDigits();
                }
                bool integer = true;
                if (Take('.'))
                {
                    integer = false;
                    RequireDigits();
                }
                if (_index < _text.Length && (_text[_index] == 'e' || _text[_index] == 'E'))
                {
                    integer = false;
                    _index++;
                    if (_index < _text.Length && (_text[_index] == '+' || _text[_index] == '-'))
                    {
                        _index++;
                    }
                    RequireDigits();
                }
                string token = _text.Substring(start, _index - start);
                if (integer && long.TryParse(token, NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture, out long whole) && Math.Abs((double)whole) <= MaxSafeInteger)
                {
                    return whole;
                }
                if (!integer && double.TryParse(token, NumberStyles.Float, CultureInfo.InvariantCulture, out double real) &&
                    !double.IsNaN(real) && !double.IsInfinity(real))
                {
                    return real;
                }
                throw Error("JSON number is invalid or outside the safe range");
            }

            private void RequireDigits()
            {
                int start = _index;
                while (_index < _text.Length && char.IsDigit(_text[_index]))
                {
                    _index++;
                }
                if (_index == start)
                {
                    throw Error("JSON number requires digits");
                }
            }

            private void ReadLiteral(string literal)
            {
                if (_index + literal.Length > _text.Length ||
                    string.CompareOrdinal(_text, _index, literal, 0, literal.Length) != 0)
                {
                    throw Error("JSON literal is invalid");
                }
                _index += literal.Length;
            }

            private bool Take(char expected)
            {
                if (_index < _text.Length && _text[_index] == expected)
                {
                    _index++;
                    return true;
                }
                return false;
            }

            private void Require(char expected)
            {
                if (!Take(expected))
                {
                    throw Error("JSON expected '" + expected + "'");
                }
            }

            private void SkipWhitespace()
            {
                while (_index < _text.Length &&
                       (_text[_index] == ' ' || _text[_index] == '\t' || _text[_index] == '\r' || _text[_index] == '\n'))
                {
                    _index++;
                }
            }

            private FormatException Error(string message)
            {
                return new FormatException(message + " at character " + _index);
            }
        }
    }
}
