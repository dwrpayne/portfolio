$(document).ready(function () {
    $("button.refresh").click(function () {
        $(this).attr('disabled', 'disabled');
        $(this).text($(this).text().replace("Refresh", "Refreshing"));
        $.ajax({
            url: window.location.pathname,
            data: 'refresh-' + $(this).attr('data-refresh-type'),
            context: this,
            success: function (data) {
                divs = $(this).attr('data-refresh-div');
                if (divs) {
                    divs = divs.split(';')
                    for (var i = 0; i < divs.length; i++) {
                        var html = $(data).closest('#' + divs[i]).html();
                        $('#' + divs[i]).html(html);
                    }
                }
            },
            error: function (data) {
                alert("Couldn't refresh!\n" + data["responseText"]);
            },
            complete: function (jqXHR, textStatus) {
                $(this).prop("disabled", false);
                $(this).text($(this).text().replace("Refreshing", "Refresh"));
            }
        });
    });
});

$(function () {
    $(".tablesorter").tablesorter();
});
