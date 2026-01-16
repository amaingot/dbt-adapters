{% materialization view, adapter='athena' -%}
	    {%- set identifier = model['alias'] -%}
	    {%- set versions_to_keep = config.get('versions_to_keep', default=4) -%}
	    {%- set is_s3_tables_catalog = database is not none and (database | lower).startswith('s3tablescatalog/') -%}
	    {%- set target_relation = api.Relation.create(identifier=identifier,
	                                                schema=schema,
	                                                database=database,
	                                                type='view') -%}

    {% set to_return = create_or_replace_view(run_outside_transaction_hooks=False) %}

	    {% if not is_s3_tables_catalog %}
	        {% do adapter.expire_glue_table_versions(target_relation, versions_to_keep, False) %}
	    {% endif %}

	    {% set target_relation = this.incorporate(type='view') %}
	    {% do persist_docs(target_relation, model) %}

    {% do return(to_return) %}
{%- endmaterialization %}
