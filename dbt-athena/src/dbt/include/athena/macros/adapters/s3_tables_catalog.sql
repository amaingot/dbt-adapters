{# Centralized S3 Tables catalog detection.
   Users can set config(is_s3_tables_catalog=true|false) to override auto-detection. #}
{% macro is_s3_tables_catalog(database) -%}
  {%- set explicit = config.get('is_s3_tables_catalog', none) -%}
  {%- if explicit is not none -%}
    {{ return(explicit | as_bool) }}
  {%- endif -%}
  {{ return(adapter.is_s3_tables_catalog(database)) }}
{%- endmacro %}
