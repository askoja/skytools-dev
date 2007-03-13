
create or replace function londiste.provider_remove_table(
    i_queue_name   text,
    i_table_name   text
) returns integer as $$
declare
    tgname text;
begin
    if londiste.link_source(i_queue_name) is not null then
        raise exception 'Linked queue, manipulation not allowed';
    end if;

    select trigger_name into tgname from londiste.provider_table
        where queue_name = i_queue_name
          and table_name = i_table_name;
    if not found then
        raise exception 'no such table registered';
    end if;

    execute 'drop trigger ' || tgname || ' on ' || i_table_name;

    delete from londiste.provider_table
        where queue_name = i_queue_name
          and table_name = i_table_name;

    return 1;
end;
$$ language plpgsql security definer;

