INSERT INTO support_member_salaries
  (user_id, effective_from, annual_salary, currency, annual_working_hours, display_name, notes)
VALUES
  ('712020:cb118ba7-1272-4096-90ff-dd55c96bb18b', '2022-08-01', 40000.00, 'GBP', 2080, 'Ezra Harvey', 'Initial salary seed')
ON CONFLICT (user_id, effective_from) DO UPDATE
SET annual_salary=EXCLUDED.annual_salary,
    currency=EXCLUDED.currency,
    annual_working_hours=EXCLUDED.annual_working_hours,
    display_name=EXCLUDED.display_name,
    notes=EXCLUDED.notes;
