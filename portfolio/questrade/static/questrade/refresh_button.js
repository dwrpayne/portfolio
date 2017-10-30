$(document).ready(function () {
    $("button.refresh").click(function () {
        $(this).attr('disabled', 'disabled');
        $(this).html("Refreshing...");
        $.ajax({
            url: 'go',
            data: 'refresh-'+$(this).attr('data-refresh-type'),
            context: this,
            success: function (data) {
                div = $(this).attr('data-refresh-type')
                var html = $(data).filter('#' + div).html();
                $('#' + div).html(html);
            },
            error: function (data) {
                alert("Couldn't refresh!\n" + JSON.stringify(data))
            },
            complete: function (jqXHR, textStatus) {
                $(this).prop("disabled", false);
                $(this).html("Refresh Balances");
            }
        });
    });
});